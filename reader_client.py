import sys
import os
import logging
import re
from reader.diagnostics import setup_client_diagnostics

from datetime import datetime
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu, QInputDialog, QMessageBox
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer, Qt, QProcess, Slot

from reader.global_card_reader import GlobalCardReader, reverse_uid_bytes
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker, RetryWorker, AddCardWorker
from worker.offline_manager import OfflineManager
from worker.device_worker import DeviceSyncWorker
from reader.identity import DeviceIdentity

logger = logging.getLogger(__name__)
DEVICE_POLL_MS = 5000
DEVICE_RETRY_MS = 30000


def client_arguments(argv):
    return "--dev-mode" in argv[1:], [argv[0], *(arg for arg in argv[1:] if arg != "--dev-mode")]


def resource_path(relative_path):
    """ 取得資源檔案的絕對路徑，相容於 PyInstaller 打包後的環境 """
    try:
        # PyInstaller 建立的臨時資料夾路徑存於 _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class PunchClient(QMainWindow):
    def __init__(self, dev_mode=False):
        super().__init__()
        self.setWindowTitle("Punch System Client")
        self.dev_mode = dev_mode

        self.enrollment_credential = ""
        self.enrollment_timer = QTimer(self)
        self.enrollment_timer.setSingleShot(True)
        self.enrollment_timer.timeout.connect(self._enrollment_timed_out)
        self.calibration_expected = ""
        self.calibration_timer = QTimer(self)
        self.calibration_timer.setSingleShot(True)
        self.calibration_timer.timeout.connect(self._calibration_timed_out)
        self.identity = DeviceIdentity()
        self.device_status = "pending"
        self.remote_paused = False
        self.device_online = False
        self._shutdown_requested = False
        self._restart_requested = False
        self._refresh_urls()

        # 1. 初始化元件
        self.worker_manager = WorkerManager(self)
        self.worker_manager.idle.connect(self._finish_shutdown)
        self.worker_manager.any_error.connect(
            lambda wid, detail: logger.error("Worker %s failed:\n%s", wid, detail)
        )
        self.offline_mgr = OfflineManager()
        self.retry_pending = bool(self.offline_mgr.load_all())
        self.reader = GlobalCardReader(threshold_ms=50)
        self.reader.uid_order = self.identity.uid_order

        # 2. 綁定硬體信號 (強制 QueuedConnection 以解決執行緒衝突問題)
        self.reader.card_scanned.connect(
            self._on_card_scanned, Qt.QueuedConnection)
        self.reader.calibration_scanned.connect(
            self._on_calibration_scanned, Qt.QueuedConnection)

        # 3. 初始化 UI & 托盤
        self.init_tray()

        # 3.5 初始化所有 Worker 訊號監聽 (只需執行一次，避免重複綁定)
        self._setup_punch_signals()
        self._setup_retry_signals()
        self._setup_add_card_signals()
        self.worker_manager.on_success(DeviceSyncWorker.WORKER_ID, self._on_device_sync)

        # 4. 定時補傳檢查 (每 5 分鐘)
        self.retry_timer = QTimer(self)
        self.retry_timer.timeout.connect(self._trigger_retry)
        self.retry_timer.start(300000)

        self.device_timer = QTimer(self)
        self.device_timer.timeout.connect(self._sync_device)
        self.device_timer.start(DEVICE_POLL_MS)
        self.shutdown_warning_timer = QTimer(self)
        self.shutdown_warning_timer.setSingleShot(True)
        self.shutdown_warning_timer.timeout.connect(self._warn_slow_shutdown)
        self._sync_device()

        # 啟動監聽
        self.reader.start()
        logger.info("Desktop reader started")

    def _refresh_urls(self):
        self.API_URL = self.identity.server_url + "/api/v1/punch"
        self.ADD_CARD_URL = self.identity.server_url + "/api/v1/cards/empty"

    def _sync_device(self):
        if self._shutdown_requested:
            return
        self.worker_manager.start(DeviceSyncWorker(self.identity))

    def _on_device_sync(self, state):
        if state.get("registered") and not self.identity.registered:
            self.identity.mark_registered()
        if state.get("status") in ("pending", "approved", "disabled", "revoked"):
            self.device_timer.setInterval(DEVICE_POLL_MS)
            old = self.device_status
            was_online = self.device_online
            self.device_online = True
            self.device_status = state["status"]
            self.remote_paused = bool(state.get("paused"))
            if self.device_status != "approved" or self.remote_paused:
                self._clear_enrollment()
            elif state.get("enrollment"):
                self.enrollment_credential = state["enrollment"]
                self.enrollment_timer.start(30000)
                self.tray.showMessage("新增卡片", "請在 30 秒內刷一張卡", QSystemTrayIcon.Information)
            if old != self.device_status:
                self.tray.showMessage("讀卡端狀態", self.device_status, QSystemTrayIcon.Information)
            if not was_online and self.retry_pending:
                self._trigger_retry()
            if state.get("restart"):
                self._restart_application()
        elif state.get("status") in ("registration_error", "auth_error"):
            self.device_timer.setInterval(DEVICE_RETRY_MS)
            self.device_online = False
            self._clear_enrollment()
            self.device_status = "invalid"
            logger.error("Device registration failed: %s", state.get("message"))
            self.tray.showMessage("讀卡端驗證失敗", "請檢查伺服器位址或重新申請裝置", QSystemTrayIcon.Warning)
        elif state.get("status") == "offline":
            self.device_timer.setInterval(DEVICE_POLL_MS)
            self.device_online = False
            self._clear_enrollment()

    def _restart_application(self):
        logger.info("Remote restart command acknowledged; draining active work")
        self._begin_shutdown(restart=True)

    def _launch_replacement(self) -> bool:
        if getattr(sys, "frozen", False):
            executable, args = sys.executable, []
        else:
            executable, args = sys.executable, [os.path.abspath(__file__)]
        if self.dev_mode:
            args.append("--dev-mode")
        try:
            started = QProcess.startDetached(executable, args)
        except Exception:
            logger.exception("Failed to launch replacement reader")
            return False
        return bool(started[0] if isinstance(started, tuple) else started)

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(resource_path("icon.png")))

        menu = QMenu(self)

        id_act = QAction(f"裝置 UUID: {self.identity.uuid}", self)
        id_act.triggered.connect(lambda: QApplication.clipboard().setText(self.identity.uuid))
        menu.addAction(id_act)
        server_act = QAction("設定伺服器位址", self)
        server_act.triggered.connect(self._set_server_url)
        menu.addAction(server_act)
        calibrate_act = QAction("校正卡號順序", self)
        calibrate_act.triggered.connect(self._start_calibration)
        menu.addAction(calibrate_act)
        if self.dev_mode:
            test_menu = QMenu("測試模式", menu)
            menu.addMenu(test_menu)
            simulate_act = test_menu.addAction("模擬讀卡")
            simulate_act.triggered.connect(self._simulate_card_scan)
        menu.addSeparator()

        quit_act = QAction("退出系統", self)
        quit_act.triggered.connect(self._safe_exit)
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _set_server_url(self):
        if self._shutdown_requested:
            return
        url, ok = QInputDialog.getText(self, "伺服器位址", "內網伺服器 URL", text=self.identity.server_url)
        if not ok:
            return
        url = url.strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "位址錯誤", "請輸入完整的 http:// 或 https:// 位址")
            return
        self.identity.set_server_url(url)
        self._clear_enrollment()
        self._refresh_urls()
        self.device_status = "pending"
        self.device_online = False
        self._sync_device()

    def _simulate_card_scan(self):
        if not self.dev_mode or self._shutdown_requested:
            return
        calibrating = bool(self.calibration_expected)
        # The global keyboard listener must not mistake typing in this dialog for a card scan.
        self.reader.stop()
        try:
            uid, ok = QInputDialog.getText(
                self, "模擬讀卡",
                ("輸入模擬讀卡機的原始 UID（尚未調整位元組順序）：" if calibrating
                 else "輸入卡號（讀卡程式處理後的 UID）：")
            )
        finally:
            if not self._shutdown_requested:
                self.reader.start()
        if self._shutdown_requested or not ok:
            return
        uid = uid.strip()
        if not uid:
            QMessageBox.warning(self, "卡號錯誤", "請輸入卡號")
            return
        if calibrating:
            # A modal dialog can outlive the 60-second calibration timer.
            if self.calibration_expected:
                self._on_calibration_scanned(uid)
            return
        self._on_card_scanned(uid)

    def _start_calibration(self):
        if self._shutdown_requested:
            return
        self.reader.stop()
        try:
            expected, ok = QInputDialog.getText(
                self, "校正卡號順序", "輸入同一張實卡的既有 UID（8、14 或 20 位十六進位）："
            )
        finally:
            if not self._shutdown_requested:
                self.reader.start()
        if self._shutdown_requested or not ok:
            return
        expected = expected.strip().upper()
        if len(expected) not in (8, 14, 20) or not re.fullmatch(r"[0-9A-F]+", expected):
            QMessageBox.warning(self, "卡號錯誤", "UID 須為 8、14 或 20 位十六進位字元")
            return
        self._clear_enrollment()
        self.identity.set_uid_order(None)
        self.reader.uid_order = None
        self.calibration_expected = expected
        self.reader.calibration_pending = True
        self.calibration_timer.start(60000)
        self.tray.showMessage("校正卡號順序", "請在 60 秒內刷剛才輸入的實卡；此刷卡不會打卡", QSystemTrayIcon.Information)

    def _on_calibration_scanned(self, raw_uid):
        if not self.calibration_expected or self._shutdown_requested:
            return
        self.calibration_timer.stop()
        self.reader.calibration_pending = False
        expected = self.calibration_expected
        self.calibration_expected = ""
        raw = raw_uid.upper()
        reversed_uid = reverse_uid_bytes(raw)
        if raw == expected:
            order = "normal"
        elif reversed_uid == expected:
            order = "reversed"
        else:
            self.tray.showMessage("UID MISMATCH", f"原始 UID：{raw}；倒序 UID：{reversed_uid}。請核對卡片後重新校正", QSystemTrayIcon.Warning)
            return
        self.identity.set_uid_order(order)
        self.reader.uid_order = order
        self.tray.showMessage("UID MATCH", f"已保存卡號順序：{'原始' if order == 'normal' else '倒序'}；UID：{expected}", QSystemTrayIcon.Information)

    def _calibration_timed_out(self):
        if self.calibration_expected:
            self.calibration_expected = ""
            self.reader.calibration_pending = False
            self.tray.showMessage("校正逾時", "60 秒內未刷卡，請重新校正卡號順序", QSystemTrayIcon.Warning)

    # ── Worker Signal Setup ──────────────────────────────────

    def _setup_punch_signals(self):
        wid = PunchWorker.WORKER_ID

        def handle_success(result: dict):
            if result["status"] == "online":
                if not self.device_online:
                    self.device_timer.start(DEVICE_POLL_MS)
                    self._sync_device()
                if self.retry_pending:
                    self._trigger_retry()
                name = result.get('employee_name', result.get('uid'))
                msg = f"{name} 於 {result.get('timestamp')} 打卡成功"
                self.tray.showMessage("打卡成功", msg, QSystemTrayIcon.Information)
            elif result["status"] == "offline":
                # 離線模式：由 OfflineManager 處理
                self.offline_mgr.save_punch(result["uid"], result["timestamp"], self.identity.uuid)
                self.retry_pending = True
                self.tray.showMessage(
                    "離線暫存", "網路連線失敗，打卡資訊已儲存於本地", QSystemTrayIcon.Warning)
            else:
                self.tray.showMessage("打卡失敗", result.get("message", "伺服器拒絕請求"), QSystemTrayIcon.Warning)

        self.worker_manager.on_success(wid, handle_success)

    def _setup_retry_signals(self):
        wid = RetryWorker.WORKER_ID

        def handle_success(res):
            self.retry_pending = bool(self.offline_mgr.load_all())
            if res["success_count"] > 0:
                self.tray.showMessage(
                    "補傳完成", f"已成功上傳 {res['success_count']} 筆離線紀錄",
                    QSystemTrayIcon.Information)

        self.worker_manager.on_success(wid, handle_success)

    def _setup_add_card_signals(self):
        def handle_success(result):
            status = result["status"]
            uid = result["uid"]
            if status == "success":
                self.tray.showMessage("新增卡片成功", f"卡號 {uid} 已建立空卡", QSystemTrayIcon.Information)
            elif status == "duplicate":
                self.tray.showMessage("新增卡片失敗", f"卡號 {uid} 已存在", QSystemTrayIcon.Warning)
            elif status == "unknown":
                self.tray.showMessage("新增結果未確認", f"卡號 {uid} 的伺服器回應無法確認，請到管理頁查詢", QSystemTrayIcon.Warning)
            else:
                self.tray.showMessage("新增卡片失敗", result["message"], QSystemTrayIcon.Warning)

        self.worker_manager.on_success(AddCardWorker.WORKER_ID, handle_success)
        self.worker_manager.on_error(
            AddCardWorker.WORKER_ID,
            lambda _error: self.tray.showMessage("新增結果未確認", "請到管理頁查詢", QSystemTrayIcon.Warning),
        )

    # ── Slots & Logic ────────────────────────────────────────

    def _clear_enrollment(self):
        self.enrollment_timer.stop()
        self.enrollment_credential = ""

    def _enrollment_timed_out(self):
        if self.enrollment_credential:
            self._clear_enrollment()
            self.tray.showMessage("新增卡片逾時", "30 秒內未刷卡，已返回打卡模式", QSystemTrayIcon.Warning)

    def _on_card_scanned(self, uid: str):
        if self._shutdown_requested or self.reader.uid_order is None:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self.device_status != "approved" or self.remote_paused:
            logger.info(f"[UI] 讀卡器已暫停，忽略卡號: {uid}")
            return

        logger.info(f"[UI] 感應卡號: {uid}")

        if self.enrollment_credential:
            credential = self.enrollment_credential
            self._clear_enrollment()
            worker = AddCardWorker(uid, self.ADD_CARD_URL, credential, self.identity)
        else:
            worker = PunchWorker(uid, now, self.API_URL, self.identity)

        if not self.worker_manager.start(worker) and isinstance(worker, AddCardWorker):
            self.tray.showMessage("新增卡片失敗", "讀卡端忙碌，請重新下達加卡命令", QSystemTrayIcon.Warning)

    def _trigger_retry(self):
        if self._shutdown_requested:
            return
        if (self.retry_pending and self.device_status == "approved" and not self.remote_paused
                and not self.worker_manager.is_running(RetryWorker.WORKER_ID)):
            worker = RetryWorker(self.API_URL, self.identity)
            self.worker_manager.start(worker)

    def _safe_exit(self):
        self._begin_shutdown(restart=False)

    def _begin_shutdown(self, restart: bool):
        self._clear_enrollment()
        self.calibration_timer.stop()
        self.calibration_expected = ""
        self.reader.calibration_pending = False
        if self._shutdown_requested:
            return
        self._shutdown_requested = True
        self._restart_requested = restart
        logger.info("Reader shutdown requested: %s", "restart" if restart else "exit")
        self.worker_manager.begin_shutdown()
        self.retry_timer.stop()
        self.device_timer.stop()
        self.reader.stop()
        # RetryWorker checks cancellation between entries and still persists
        # removals for entries uploaded before cancellation.
        self.worker_manager.cancel(RetryWorker.WORKER_ID)
        if self.worker_manager.has_workers():
            self.shutdown_warning_timer.start(10000)
        else:
            self._finish_shutdown()

    def _warn_slow_shutdown(self):
        logger.warning("Still waiting for workers before exit: %s", self.worker_manager.running_ids())

    @Slot()
    def _finish_shutdown(self):
        if not self._shutdown_requested or self.worker_manager.has_workers():
            return
        self.shutdown_warning_timer.stop()
        if self._restart_requested:
            if self._launch_replacement():
                logger.info("Replacement reader launched; exiting old process")
            else:
                logger.error("Replacement reader did not start; resuming this process")
                self.tray.showMessage("重啟失敗", "無法啟動新的讀卡程式，現有程式繼續運作", QSystemTrayIcon.Critical)
                self._shutdown_requested = False
                self._restart_requested = False
                self.worker_manager.resume()
                self.retry_timer.start(300000)
                self.device_timer.start(DEVICE_POLL_MS)
                self.reader.start()
                return
        else:
            logger.info("Reader exited normally")
        self._quit_application()

    def _quit_application(self):
        QApplication.quit()


if __name__ == "__main__":
    client_log_dir = setup_client_diagnostics()
    logger.info("Desktop reader starting; logs=%s", client_log_dir)
    dev_mode, qt_argv = client_arguments(sys.argv)
    app = QApplication(qt_argv)
    app.setQuitOnLastWindowClosed(False)
    client = PunchClient(dev_mode=dev_mode)
    sys.exit(app.exec())
