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
from PySide6.QtCore import QTimer, Qt

from reader.global_card_reader import GlobalCardReader  # 前文定義的全域監聽類別
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker, RetryWorker, AddCardWorker
from worker.offline_manager import OfflineManager

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
    # 從環境變數讀取 API 基礎路徑，並動態生成子路徑
    _API_PORT = os.getenv("CVTA_CLOCKIN_API_PORT", "16688")
    _BASE_URL = os.getenv("CVTA_CLOCKIN_API_URL",
                          "http://127.0.0.1").rstrip("/")
    _BASE_URL = f"{_BASE_URL}:{_API_PORT}"
    API_URL = f"{_BASE_URL}/api/v1/punch"
    ADD_CARD_URL = f"{_BASE_URL}/api/v1/cards/empty"
    LOGIN_URL = f"{_BASE_URL}/api/v1/login"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Punch System Client")

        # 管理員狀態
        self.is_admin_mode = False
        self._reader_suspended = False  # 新增：用於暫停讀卡處理的旗標
        self.admin_token = ""  # 實務上應透過登入對話框獲取

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

        # 4. 定時補傳檢查 (每 5 分鐘)
        self.retry_timer = QTimer(self)
        self.retry_timer.timeout.connect(self._trigger_retry)
        self.retry_timer.start(300000)

        # 啟動監聽
        self.reader.start()

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon(resource_path("icon.png")))

        menu = QMenu()

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

    # ── Worker Signal Setup ──────────────────────────────────

    def _setup_punch_signals(self):
        wid = PunchWorker.WORKER_ID

        def handle_success(result: dict):
            if result["status"] == "online":
                name = result.get('employee_name', result.get('uid'))
                msg = f"{name} 於 {result.get('timestamp')} 打卡成功"
                self.tray.showMessage("打卡成功", msg, QSystemTrayIcon.Information)
            else:
                # 離線模式：由 OfflineManager 處理
                self.offline_mgr.save_punch(result["uid"], result["timestamp"])
                self.tray.showMessage(
                    "離線暫存", "網路連線失敗，打卡資訊已儲存於本地", QSystemTrayIcon.Warning)

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
            # 登入時暫停處理訊號，避免感應觸發打卡邏輯
            self._reader_suspended = True

            dialog = LoginDialog(self.LOGIN_URL, self)
            result = dialog.exec()

            # 對話框關閉後恢復處理
            self._reader_suspended = False

            if result == QDialog.Accepted:
                self.admin_token = dialog.get_token()
                self.is_admin_mode = True
                logger.info(f"管理員 Token: {self.admin_token}")
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

        if self._reader_suspended:
            logger.info(f"[UI] 讀卡器已暫停，忽略卡號: {uid}")
            return

        logger.info(f"[UI] 感應卡號: {uid}")

        if self.is_admin_mode:
            if not self.admin_token:
                self.tray.showMessage(
                    "提示", "請先設定管理員 Token", QSystemTrayIcon.Warning)
                return
            worker = AddCardWorker(uid, self.ADD_CARD_URL, self.admin_token)
        else:
            worker = PunchWorker(uid, now, self.API_URL)

        self.worker_manager.start(worker)

    def _trigger_retry(self):
        if not self.worker_manager.is_running(RetryWorker.WORKER_ID):
            worker = RetryWorker(self.API_URL)
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
