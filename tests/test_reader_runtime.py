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
from worker.worker_base import BaseWorker
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker


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
    def showMessage(self, *args):
        pass


class FakeIdentity:
    uuid = "test-device"
    secret = "0" * 64
    server_url = "http://127.0.0.1:16688"
    registered = True


class FakeOfflineManager:
    def __init__(self):
        self.saved = []

    def save_punch(self, uid, timestamp, device_uuid):
        self.saved.append((uid, timestamp, device_uuid))


class FakeReader(QObject):
    card_scanned = Signal(str)

    def __init__(self, threshold_ms=50):
        super().__init__()

    def start(self):
        pass

    def stop(self):
        pass


class TestClient(reader_client.PunchClient):
    def _sync_device(self):
        pass

    def init_tray(self):
        self.tray = FakeTray()


class ReaderRuntimeTests(unittest.TestCase):
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
