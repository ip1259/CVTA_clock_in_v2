"""Desktop reader lifetime regressions (run with QT_QPA_PLATFORM=offscreen)."""

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

import reader_client
from reader.diagnostics import client_log_dir
from reader.global_card_reader import GlobalCardReader
from reader.identity import DeviceIdentity
from worker.worker_base import BaseWorker
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker, RetryWorker, AddCardWorker


APP = QApplication.instance() or QApplication([])


def spin_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        APP.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    APP.processEvents()
    return predicate()


class GateWorker(BaseWorker):
    WORKER_ID = "gate"

    def __init__(self, gate, result="done"):
        super().__init__()
        self.gate = gate
        self.result = result

    def execute(self):
        self.gate.wait(2)
        return self.result


class FakeTray:
    def __init__(self):
        self.messages = []

    def showMessage(self, *args):
        self.messages.append(args)


class FakeIdentity:
    uuid = "test-device"
    secret = "0" * 64
    server_url = "http://127.0.0.1:16688"
    registered = True
    uid_order = "reversed"

    def set_uid_order(self, order):
        self.uid_order = order


class FakeOfflineManager:
    def __init__(self):
        self.saved = []

    def save_punch(self, uid, timestamp, device_uuid):
        self.saved.append((uid, timestamp, device_uuid))

    def load_all(self):
        return list(self.saved)


class FakeReader(QObject):
    card_scanned = Signal(str)
    calibration_scanned = Signal(str)

    def __init__(self, threshold_ms=50):
        super().__init__()
        self.starts = 0
        self.stops = 0
        self.calibration_pending = False

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class TestClient(reader_client.PunchClient):
    def _sync_device(self):
        pass

    def init_tray(self):
        self.tray = FakeTray()


class MenuTestClient(reader_client.PunchClient):
    def _sync_device(self):
        pass


class ReaderRuntimeTests(unittest.TestCase):
    def test_calibration_is_available_without_dev_mode_and_consumes_scan(self):
        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=FakeOfflineManager()),
              patch.object(reader_client, "GlobalCardReader", FakeReader)):
            client = MenuTestClient()
            try:
                messages = []
                client.tray.showMessage = lambda *args: messages.append(args)
                action = next(action for action in client.tray.contextMenu().actions()
                              if action.text() == "校正卡號順序")
                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)), \
                     patch.object(client, "_on_card_scanned") as punch:
                    action.trigger()
                    self.assertTrue(client.reader.calibration_pending)
                    self.assertIsNone(client.reader.uid_order)
                    client.reader.calibration_scanned.emit("D4C3B2A1")
                    APP.processEvents()
                    punch.assert_not_called()
                self.assertEqual(client.reader.uid_order, "reversed")
                self.assertEqual(client.identity.uid_order, "reversed")
                self.assertFalse(client.calibration_timer.isActive())
                self.assertTrue(any(message[0] == "UID MATCH" for message in messages))

                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    action.trigger()
                client.reader.calibration_scanned.emit("A1B2C3D4")
                APP.processEvents()
                self.assertEqual(client.reader.uid_order, "normal")

                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    action.trigger()
                client.reader.calibration_scanned.emit("11223344")
                APP.processEvents()
                self.assertIsNone(client.reader.uid_order)
                self.assertTrue(any(message[0] == "UID MISMATCH" for message in messages))
                client._on_card_scanned("A1B2C3D4")
                self.assertFalse(client.worker_manager.has_workers())
                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    action.trigger()
                client._calibration_timed_out()
                self.assertFalse(client.reader.calibration_pending)
                self.assertIsNone(client.reader.uid_order)
                self.assertTrue(any(message[0] == "校正逾時" for message in messages))
            finally:
                client.calibration_timer.stop()
                client.reader.stop()

    def test_dev_mode_requires_startup_flag(self):
        self.assertEqual(reader_client.client_arguments(["reader_client.exe"]),
                         (False, ["reader_client.exe"]))
        self.assertEqual(reader_client.client_arguments(["reader_client.exe", "--dev-mode", "-platform", "offscreen"]),
                         (True, ["reader_client.exe", "-platform", "offscreen"]))

    def test_simulated_scan_completes_calibration_without_punch(self):
        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=FakeOfflineManager()),
              patch.object(reader_client, "GlobalCardReader", FakeReader)):
            client = MenuTestClient(dev_mode=True)
            try:
                menu = client.tray.contextMenu()
                calibrate = next(action for action in menu.actions()
                                 if action.text() == "校正卡號順序")
                test_menu = next(action.menu() for action in menu.actions()
                                 if action.text() == "測試模式")
                simulate = test_menu.actions()[0]
                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    calibrate.trigger()
                with patch.object(reader_client.QInputDialog, "getText", return_value=("D4C3B2A1", True)) as dialog, \
                     patch.object(client, "_on_card_scanned") as punch:
                    simulate.trigger()
                    self.assertIn("原始 UID", dialog.call_args.args[2])
                    punch.assert_not_called()
                self.assertEqual(client.identity.uid_order, "reversed")
                self.assertFalse(client.calibration_expected)
                self.assertFalse(client.worker_manager.has_workers())

                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    calibrate.trigger()
                with patch.object(reader_client.QInputDialog, "getText", return_value=("", False)), \
                     patch.object(client, "_on_card_scanned") as punch:
                    simulate.trigger()
                    punch.assert_not_called()
                self.assertTrue(client.calibration_expected)

                def expire_during_dialog(*_args):
                    client._calibration_timed_out()
                    return "A1B2C3D4", True
                with patch.object(reader_client.QInputDialog, "getText", side_effect=expire_during_dialog), \
                     patch.object(client, "_on_card_scanned") as punch:
                    simulate.trigger()
                    punch.assert_not_called()
                self.assertIsNone(client.reader.uid_order)

                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)):
                    calibrate.trigger()
                with patch.object(reader_client.QInputDialog, "getText", return_value=("A1B2C3D4", True)), \
                     patch.object(client, "_on_card_scanned") as punch:
                    simulate.trigger()
                    punch.assert_not_called()
                self.assertEqual(client.identity.uid_order, "normal")
            finally:
                client.calibration_timer.stop()
                client.reader.stop()

    def test_simulated_scan_uses_card_scan_path(self):
        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=FakeOfflineManager()),
              patch.object(reader_client, "GlobalCardReader", FakeReader)):
            client = MenuTestClient()
            try:
                self.assertFalse(any(action.text() == "測試模式"
                                     for action in client.tray.contextMenu().actions()))
                with patch.object(reader_client.QInputDialog, "getText") as dialog:
                    client._simulate_card_scan()
                    dialog.assert_not_called()
            finally:
                client.reader.stop()

            client = MenuTestClient(dev_mode=True)
            try:
                with patch.object(reader_client.QProcess, "startDetached", return_value=True) as launch:
                    self.assertTrue(client._launch_replacement())
                    self.assertEqual(launch.call_args.args[1][-1], "--dev-mode")
                test_menu = next(action.menu() for action in client.tray.contextMenu().actions()
                                 if action.text() == "測試模式")
                (simulate,) = test_menu.actions()
                self.assertTrue(simulate.isVisible())
                with patch.object(reader_client.QInputDialog, "getText", return_value=(" 1234 ", True)), \
                     patch.object(client, "_on_card_scanned") as scanned:
                    simulate.trigger()
                    scanned.assert_called_once_with("1234")
                self.assertEqual((client.reader.starts, client.reader.stops), (2, 1))
                with patch.object(reader_client.QInputDialog, "getText", return_value=("", False)), \
                     patch.object(client, "_on_card_scanned") as scanned:
                    simulate.trigger()
                    scanned.assert_not_called()
                with patch.object(reader_client.QInputDialog, "getText", return_value=("  ", True)), \
                     patch.object(reader_client.QMessageBox, "warning") as warning, \
                     patch.object(client, "_on_card_scanned") as scanned:
                    simulate.trigger()
                    warning.assert_called_once()
                    scanned.assert_not_called()
            finally:
                client.reader.stop()

    def test_add_card_worker_reports_signed_server_result(self):
        from device_protocol import response_signature

        def run(status):
            def respond(request):
                body = b'{"detail":"test"}' if status != 200 else b'{"status":"ok"}'
                signature = response_signature(FakeIdentity.secret,
                                               request.headers["X-Device-Nonce"], status, body)
                return httpx.Response(status, content=body,
                                      headers={"X-Device-Response-Signature": signature})
            real_client = httpx.Client
            with patch("worker.punch_worker.httpx.Client",
                       side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(respond))):
                return AddCardWorker("1234", "http://example.test/api/v1/cards/empty",
                                     "a" * 64, FakeIdentity()).execute()

        self.assertEqual(run(200)["status"], "success")
        self.assertEqual(run(400)["status"], "duplicate")
        self.assertEqual(run(403)["status"], "error")

        real_client = httpx.Client
        with patch("worker.punch_worker.httpx.Client",
                   side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(
                       lambda request: httpx.Response(200, json={"status": "ok"})))):
            self.assertEqual(AddCardWorker("1234", "http://example.test/api/v1/cards/empty",
                                           "a" * 64, FakeIdentity()).execute()["status"], "unknown")

    def test_recovery_triggers_pending_retry_without_waiting_for_timer(self):
        offline = FakeOfflineManager()
        offline.save_punch("1234", "2026-10-20 10:00:00", FakeIdentity.uuid)
        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=offline),
              patch.object(reader_client, "GlobalCardReader", FakeReader)):
            client = TestClient()
            try:
                with patch.object(client, "_trigger_retry") as retry, patch.object(client, "_sync_device") as sync:
                    client._on_device_sync({"status": "approved", "paused": False})
                    retry.assert_called_once()
                    client._on_device_sync({"status": "offline"})
                    self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_POLL_MS)
                    client._on_device_sync({"status": "auth_error", "message": "invalid"})
                    self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_RETRY_MS)
                    client._on_device_sync({"status": "approved", "paused": False})
                    self.assertEqual(retry.call_count, 2)
                    client._on_device_sync({"status": "offline"})
                    client.worker_manager.any_success.emit(
                        PunchWorker.WORKER_ID,
                        {"status": "online", "uid": "5678", "timestamp": "2026-10-20 10:01:00"},
                    )
                    self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_POLL_MS)
                    sync.assert_called_once()
                    self.assertEqual(retry.call_count, 3)
            finally:
                client.reader.stop()

    def test_offline_retry_stops_after_first_connection_failure(self):
        pending = [{"uid": str(i), "timestamp": "2026-10-20 10:00:00",
                    "device_uuid": FakeIdentity.uuid} for i in range(3)]
        manager = type("FakeManager", (), {"load_all": lambda self: pending,
                                          "remove_punches": lambda self, items: None})()
        failure = httpx.ConnectTimeout("simulated timeout")
        with (patch("worker.punch_worker.OfflineManager", return_value=manager),
              patch("worker.punch_worker.signed_request", side_effect=failure) as send):
            self.assertEqual(RetryWorker("http://example.test/api/v1/punch", FakeIdentity()).execute(),
                             {"success_count": 0})
        self.assertEqual(send.call_count, 1)

    def test_network_timeout_becomes_offline_punch(self):
        def timeout(request):
            raise httpx.ConnectTimeout("simulated timeout", request=request)

        real_client = httpx.Client
        with patch("worker.punch_worker.httpx.Client",
                   side_effect=lambda **kwargs: real_client(transport=httpx.MockTransport(timeout))):
            result = PunchWorker("1234", "2026-10-20 10:00:00", "http://example.test/api/v1/punch",
                                 FakeIdentity()).execute()
        self.assertEqual(result, {"status": "offline", "uid": "1234",
                                  "timestamp": "2026-10-20 10:00:00"})

    def test_worker_error_contains_traceback(self):
        class FailingWorker(BaseWorker):
            WORKER_ID = "failure"

            def execute(self):
                raise RuntimeError("simulated network failure")

        manager = WorkerManager()
        errors = []
        manager.on_error("failure", errors.append)
        self.assertTrue(manager.start(FailingWorker()))
        self.assertTrue(spin_until(lambda: not manager.has_workers()))
        self.assertEqual(len(errors), 1)
        self.assertIn("RuntimeError: simulated network failure", errors[0])
        self.assertIn("Traceback (most recent call last)", errors[0])

    def test_worker_is_retained_until_qthread_finished(self):
        manager = WorkerManager()
        gate = threading.Event()
        first = GateWorker(gate)
        results = []
        manager.on_success("gate", results.append)
        self.assertTrue(manager.start(first))
        self.assertFalse(manager.start(GateWorker(threading.Event())))
        self.assertTrue(manager.has_workers())
        gate.set()
        self.assertTrue(spin_until(lambda: not manager.has_workers()))
        self.assertEqual(results, ["done"])
        second_gate = threading.Event()
        second_gate.set()
        self.assertTrue(manager.start(GateWorker(second_gate, "again")))
        self.assertTrue(spin_until(lambda: not manager.has_workers()))
        self.assertEqual(results, ["done", "again"])

    def test_shutdown_waits_for_offline_result_and_rejects_late_card(self):
        gate = threading.Event()
        offline = FakeOfflineManager()

        class OfflinePunch(GateWorker):
            WORKER_ID = "punch_task"
            started = 0

            def __init__(self, uid, timestamp, api_url, identity):
                type(self).started += 1
                super().__init__(gate, {"status": "offline", "uid": uid, "timestamp": timestamp})

        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=offline),
              patch.object(reader_client, "GlobalCardReader", FakeReader),
              patch.object(reader_client, "PunchWorker", OfflinePunch)):
            client = TestClient()
            try:
                with patch.object(client, "_quit_application") as quit_app:
                    client.device_status = "approved"
                    client._on_card_scanned("1234")
                    self.assertEqual(OfflinePunch.started, 1)
                    client._safe_exit()
                    client.reader.card_scanned.emit("5678")
                    APP.processEvents()
                    self.assertEqual(OfflinePunch.started, 1)
                    quit_app.assert_not_called()
                    gate.set()
                    self.assertTrue(spin_until(lambda: quit_app.called))
                    self.assertEqual(len(offline.saved), 1)
                    self.assertEqual(offline.saved[0][0], "1234")
                    self.assertFalse(client.worker_manager.has_workers())
            finally:
                gate.set()
                spin_until(lambda: not client.worker_manager.has_workers())
                client.reader.stop()

    def test_remote_restart_launches_after_work_drains(self):
        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=FakeOfflineManager()),
              patch.object(reader_client, "GlobalCardReader", FakeReader)):
            client = TestClient()
            gate = threading.Event()
            try:
                self.assertTrue(client.worker_manager.start(GateWorker(gate)))
                with (patch.object(client, "_launch_replacement", return_value=True) as launch,
                      patch.object(client, "_quit_application") as quit_app):
                    client._restart_application()
                    launch.assert_not_called()
                    gate.set()
                    self.assertTrue(spin_until(lambda: quit_app.called))
                    launch.assert_called_once()
            finally:
                gate.set()
                spin_until(lambda: not client.worker_manager.has_workers())
                client.reader.stop()

    def test_remote_enrollment_consumes_first_scan_without_punch(self):
        submitted = []
        class FakeAddCard(GateWorker):
            WORKER_ID = "add_card_task"
            def __init__(self, uid, api_url, credential, identity):
                submitted.append((uid, credential))
                gate = threading.Event()
                gate.set()
                super().__init__(gate, {"status": "success", "uid": uid})

        class FakePunch(GateWorker):
            WORKER_ID = "punch_task"
            started = 0
            def __init__(self, uid, timestamp, api_url, identity):
                type(self).started += 1
                gate = threading.Event()
                gate.set()
                super().__init__(gate, {"status": "error", "message": "test"})

        with (patch.object(reader_client, "DeviceIdentity", return_value=FakeIdentity()),
              patch.object(reader_client, "OfflineManager", return_value=FakeOfflineManager()),
              patch.object(reader_client, "GlobalCardReader", FakeReader),
              patch.object(reader_client, "AddCardWorker", FakeAddCard),
              patch.object(reader_client, "PunchWorker", FakePunch)):
            client = TestClient()
            try:
                client._on_device_sync({"status": "approved", "paused": False,
                                        "enrollment": "a" * 64})
                self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_POLL_MS)
                client._on_card_scanned("1234")
                self.assertEqual(submitted, [("1234", "a" * 64)])
                self.assertFalse(client.enrollment_credential)
                self.assertEqual(FakePunch.started, 0)
                self.assertTrue(spin_until(lambda: not client.worker_manager.has_workers()))
                self.assertTrue(any(message[0] == "新增卡片成功" for message in client.tray.messages))
                client.worker_manager.any_success.emit(
                    FakeAddCard.WORKER_ID, {"status": "duplicate", "uid": "1234"})
                self.assertTrue(any(message[0] == "新增卡片失敗" for message in client.tray.messages))
                client._on_card_scanned("5678")
                self.assertEqual(FakePunch.started, 1)
                client._on_device_sync({"status": "approved", "paused": False,
                                        "enrollment": "b" * 64})
                client.enrollment_timer.timeout.emit()
                self.assertFalse(client.enrollment_credential)
                self.assertTrue(any(message[0] == "新增卡片逾時" for message in client.tray.messages))
                client._on_device_sync({"status": "offline"})
                self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_POLL_MS)
                client._on_device_sync({"status": "approved", "paused": False})
                self.assertEqual(client.device_timer.interval(), reader_client.DEVICE_POLL_MS)
            finally:
                spin_until(lambda: not client.worker_manager.has_workers())
                client.reader.stop()

    def test_keyboard_callback_only_queues_input(self):
        from pynput import keyboard

        reader = GlobalCardReader()
        reader._stopped = False
        scanned = []
        reader.card_scanned.connect(scanned.append)
        try:
            def send_keys():
                for char in "1234":
                    reader._on_press(keyboard.KeyCode.from_char(char))
                reader._on_press(keyboard.Key.enter)

            thread = threading.Thread(target=send_keys)
            thread.start()
            thread.join()
            self.assertEqual(reader.key_buffer, [])
            self.assertTrue(spin_until(lambda: bool(scanned)))
            self.assertEqual(scanned, ["3412"])
            reader.stop()
            reader._on_press(keyboard.KeyCode.from_char("5"))
            APP.processEvents()
            self.assertEqual(reader.key_buffer, [])
        finally:
            reader.stop()

    def test_reader_calibration_scan_bypasses_punch_and_changes_order(self):
        reader = GlobalCardReader()
        reader._stopped = False
        scanned, calibration = [], []
        reader.card_scanned.connect(scanned.append)
        reader.calibration_scanned.connect(calibration.append)
        try:
            reader.calibration_pending = True
            reader.uid_order = None
            for char in "D4C3B2A1":
                reader._record_key(char, False)
            reader._on_input_finished()
            self.assertEqual(calibration, ["D4C3B2A1"])
            self.assertEqual(scanned, [])
            reader.uid_order = "normal"
            for char in "a1b2c3d4":
                reader._record_key(char, False)
            reader._on_input_finished()
            self.assertEqual(scanned, ["A1B2C3D4"])
        finally:
            reader.stop()

    def test_uid_order_persists_in_temporary_identity(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "device.json"
            identity = DeviceIdentity(path)
            self.assertEqual(identity.uid_order, "reversed")
            identity.set_uid_order(None)
            self.assertIsNone(DeviceIdentity(path).uid_order)
            identity.set_uid_order("normal")
            self.assertEqual(DeviceIdentity(path).uid_order, "normal")

    def test_log_path_does_not_depend_on_working_directory(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.dict(os.environ, {"LOCALAPPDATA": root}):
                expected = Path(root) / "CVTAClockIn" / "logs"
                self.assertEqual(client_log_dir(), expected)

    def test_windowed_logging_writes_outside_working_directory(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            other_cwd = base / "other"
            other_cwd.mkdir()
            env = dict(os.environ, LOCALAPPDATA=str(base),
                       PYTHONPATH=str(Path(__file__).resolve().parents[1]))
            code = (
                "import sys, logging; sys.stdout = None; "
                "from reader.diagnostics import setup_client_diagnostics; "
                "setup_client_diagnostics(); "
                "logging.getLogger('probe').error('reader-diagnostic-marker')"
            )
            result = subprocess.run([sys.executable, "-c", code], cwd=other_cwd,
                                    env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            logs = base / "CVTAClockIn" / "logs"
            self.assertIn("reader-diagnostic-marker", (logs / "error.log").read_text(encoding="utf-8"))
            self.assertTrue((logs / "crash.log").exists())
            self.assertFalse((other_cwd / "logs").exists())


if __name__ == "__main__":
    unittest.main()
