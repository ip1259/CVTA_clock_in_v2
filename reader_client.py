import sys
import os
import httpx
import logging
from log_config import setup_logging

from datetime import datetime
from PySide6.QtWidgets import (QApplication, QMainWindow, QSystemTrayIcon,
                               QMenu, QDialog, QVBoxLayout, QLineEdit,
                               QPushButton, QLabel)
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer, Qt, QProcess

from reader.global_card_reader import GlobalCardReader  # 前文定義的全域監聽類別
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker, RetryWorker, AddCardWorker
from worker.offline_manager import OfflineManager
from worker.device_worker import DeviceSyncWorker
from reader.identity import DeviceIdentity

logger = logging.getLogger(__name__)

def resource_path(relative_path):
    """ 取得資源檔案的絕對路徑，相容於 PyInstaller 打包後的環境 """
    try:
        # PyInstaller 建立的臨時資料夾路徑存於 _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


class LoginDialog(QDialog):
    """管理員登入對話框"""

    def __init__(self, login_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("管理員驗證")
        self.setFixedSize(250, 180)
        self.login_url = login_url
        self.token = ""

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("管理員帳號:"))
        self.user_input = QLineEdit()
        layout.addWidget(self.user_input)

        layout.addWidget(QLabel("密碼:"))
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.pass_input)

        self.login_btn = QPushButton("登入")
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

    def handle_login(self):
        user = self.user_input.text()
        pwd = self.pass_input.text()

        try:
            resp = httpx.post(self.login_url, json={
                              "username": user, "password": pwd}, timeout=5.0)
            if resp.status_code == 200:
                self.token = resp.json().get("access_token", "")
                self.accept()
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(self, "錯誤", "帳號或密碼錯誤")
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "連線錯誤", f"無法連線到伺服器: {e}")

    def get_token(self):
        return self.token


class PunchClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Punch System Client")

        # 管理員狀態
        self.is_admin_mode = False
        self._reader_suspended = False  # 新增：用於暫停讀卡處理的旗標
        self.admin_token = ""  # 實務上應透過登入對話框獲取
        self.identity = DeviceIdentity()
        self.device_status = "pending"
        self.remote_paused = False
        self._refresh_urls()

        # 1. 初始化元件
        self.worker_manager = WorkerManager(self)
        self.offline_mgr = OfflineManager()
        self.reader = GlobalCardReader(threshold_ms=50)

        # 2. 綁定硬體信號 (強制 QueuedConnection 以解決執行緒衝突問題)
        self.reader.card_scanned.connect(
            self._on_card_scanned, Qt.QueuedConnection)

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
        self.device_timer.start(30000)
        self._sync_device()

        # 啟動監聽
        self.reader.start()

    def _refresh_urls(self):
        self.API_URL = self.identity.server_url + "/api/v1/punch"
        self.ADD_CARD_URL = self.identity.server_url + "/api/v1/cards/empty"
        self.LOGIN_URL = self.identity.server_url + "/api/v1/login"

    def _sync_device(self):
        self.worker_manager.start(DeviceSyncWorker(self.identity))

    def _on_device_sync(self, state):
        if state.get("registered") and not self.identity.registered:
            self.identity.mark_registered()
        if state.get("status") in ("pending", "approved", "disabled", "revoked"):
            old = self.device_status
            self.device_status = state["status"]
            self.remote_paused = bool(state.get("paused"))
            if old != self.device_status:
                self.tray.showMessage("讀卡端狀態", self.device_status, QSystemTrayIcon.Information)
            if state.get("restart"):
                self._restart_application()
        elif state.get("status") in ("registration_error", "auth_error"):
            self.device_status = "invalid"
            logger.error("Device registration failed: %s", state.get("message"))
            self.tray.showMessage("讀卡端驗證失敗", "請檢查伺服器位址或重新申請裝置", QSystemTrayIcon.Warning)

    def _restart_application(self):
        if getattr(sys, "frozen", False):
            executable, args = sys.executable, []
        else:
            executable, args = sys.executable, [os.path.abspath(__file__)]
        started = QProcess.startDetached(executable, args)
        if (started[0] if isinstance(started, tuple) else started):
            self._safe_exit()

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(resource_path("icon.png")))

        menu = QMenu()

        id_act = QAction(f"裝置 UUID: {self.identity.uuid}", self)
        id_act.triggered.connect(lambda: QApplication.clipboard().setText(self.identity.uuid))
        menu.addAction(id_act)
        server_act = QAction("設定伺服器位址", self)
        server_act.triggered.connect(self._set_server_url)
        menu.addAction(server_act)
        menu.addSeparator()

        # 新增模式切換
        self.admin_act = QAction("管理員新增卡片模式", self, checkable=True)
        self.admin_act.triggered.connect(self._toggle_admin_mode)
        menu.addAction(self.admin_act)

        menu.addSeparator()

        quit_act = QAction("退出系統", self)
        quit_act.triggered.connect(self._safe_exit)
        menu.addAction(quit_act)

        self.tray.setContextMenu(menu)
        self.tray.show()

    def _set_server_url(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        url, ok = QInputDialog.getText(self, "伺服器位址", "內網伺服器 URL", text=self.identity.server_url)
        if not ok:
            return
        url = url.strip().rstrip("/")
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.warning(self, "位址錯誤", "請輸入完整的 http:// 或 https:// 位址")
            return
        self.identity.set_server_url(url)
        self._refresh_urls()
        self.device_status = "pending"
        self._sync_device()

    # ── Worker Signal Setup ──────────────────────────────────

    def _setup_punch_signals(self):
        wid = PunchWorker.WORKER_ID

        def handle_success(result: dict):
            if result["status"] == "online":
                name = result.get('employee_name', result.get('uid'))
                msg = f"{name} 於 {result.get('timestamp')} 打卡成功"
                self.tray.showMessage("打卡成功", msg, QSystemTrayIcon.Information)
            elif result["status"] == "offline":
                # 離線模式：由 OfflineManager 處理
                self.offline_mgr.save_punch(result["uid"], result["timestamp"], self.identity.uuid)
                self.tray.showMessage(
                    "離線暫存", "網路連線失敗，打卡資訊已儲存於本地", QSystemTrayIcon.Warning)
            else:
                self.tray.showMessage("打卡失敗", result.get("message", "伺服器拒絕請求"), QSystemTrayIcon.Warning)

        self.worker_manager.on_success(wid, handle_success)
        self.worker_manager.on_error(
            wid, lambda err: logger.error(f"Punch Task Error: {err}"))

    def _setup_retry_signals(self):
        wid = RetryWorker.WORKER_ID

        def handle_success(res):
            if res["success_count"] > 0:
                self.tray.showMessage(
                    "補傳完成", f"已成功上傳 {res['success_count']} 筆離線紀錄",
                    QSystemTrayIcon.Information)

        self.worker_manager.on_success(wid, handle_success)

    def _setup_add_card_signals(self):
        wid = AddCardWorker.WORKER_ID

        def handle_success(result: dict):
            if result["status"] == "success":
                self.tray.showMessage(
                    "新增成功", f"卡號 {result['uid']} 已註冊為空卡", QSystemTrayIcon.Information)
            else:
                self.tray.showMessage(
                    "新增失敗", result["message"], QSystemTrayIcon.Critical)

        self.worker_manager.on_success(wid, handle_success)
        self.worker_manager.on_error(
            wid, lambda err: self.tray.showMessage("系統錯誤", str(err), QSystemTrayIcon.Critical))

    # ── Slots & Logic ────────────────────────────────────────

    def _toggle_admin_mode(self, checked):
        if checked:
            if self.device_status != "approved" or self.remote_paused:
                self.admin_act.setChecked(False)
                self.tray.showMessage("裝置未啟用", "請先由後台核准並啟用讀卡端", QSystemTrayIcon.Warning)
                return
            # 登入時暫停處理訊號，避免感應觸發打卡邏輯
            self._reader_suspended = True

            dialog = LoginDialog(self.LOGIN_URL, self)
            result = dialog.exec()

            # 對話框關閉後恢復處理
            self._reader_suspended = False

            if result == QDialog.Accepted:
                self.admin_token = dialog.get_token()
                self.is_admin_mode = True
                logger.info("管理員新增卡片模式 已開啟")
                self.tray.showMessage(
                    "模式切換", "管理員新增卡片模式 已開啟", QSystemTrayIcon.Information)
            else:
                # 取消登入或失敗，強制取消勾選
                self.admin_act.setChecked(False)
                self.is_admin_mode = False
        else:
            self.admin_token = ""
            self.is_admin_mode = False
            self.tray.showMessage("模式切換", "管理員新增卡片模式 已關閉",
                                  QSystemTrayIcon.Information)

    def _on_card_scanned(self, uid: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if self._reader_suspended or self.device_status != "approved" or self.remote_paused:
            logger.info(f"[UI] 讀卡器已暫停，忽略卡號: {uid}")
            return

        logger.info(f"[UI] 感應卡號: {uid}")

        if self.is_admin_mode:
            if not self.admin_token:
                self.tray.showMessage(
                    "提示", "請先設定管理員 Token", QSystemTrayIcon.Warning)
                return
            worker = AddCardWorker(uid, self.ADD_CARD_URL, self.admin_token, self.identity)
        else:
            worker = PunchWorker(uid, now, self.API_URL, self.identity)

        self.worker_manager.start(worker)

    def _trigger_retry(self):
        if self.device_status == "approved" and not self.remote_paused and not self.worker_manager.is_running(RetryWorker.WORKER_ID):
            worker = RetryWorker(self.API_URL, self.identity)
            self.worker_manager.start(worker)

    def _safe_exit(self):
        self.reader.stop()
        self.worker_manager.cancel_all()
        QApplication.quit()


if __name__ == "__main__":
    setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    client = PunchClient()
    sys.exit(app.exec())
