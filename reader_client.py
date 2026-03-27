import sys
import logging
from datetime import datetime
from PySide6.QtWidgets import QApplication, QMainWindow, QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon, QAction
from PySide6.QtCore import QTimer

from reader.global_card_reader import GlobalCardReader  # 前文定義的全域監聽類別
from worker.worker_manager import WorkerManager
from worker.punch_worker import PunchWorker, RetryWorker
from worker.offline_manager import OfflineManager

logger = logging.getLogger(__name__)


class PunchClient(QMainWindow):
    API_URL = "http://127.0.0.1:8000/api/v1/punch"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Punch System Client")

        # 1. 初始化元件
        self.worker_manager = WorkerManager(self)
        self.offline_mgr = OfflineManager()
        self.reader = GlobalCardReader(threshold_ms=50)

        # 2. 綁定硬體信號
        self.reader.card_scanned.connect(self._on_card_scanned)

        # 3. 初始化 UI & 托盤
        self.init_tray()

        # 4. 定時補傳檢查 (每 5 分鐘)
        self.retry_timer = QTimer(self)
        self.retry_timer.timeout.connect(self._trigger_retry)
        self.retry_timer.start(300000)

        # 啟動監聽
        self.reader.start()

    def init_tray(self):
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(QIcon("icon.png"))  # 請準備 icon 檔案

        menu = QMenu()
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
                data = result["data"]
                msg = f"{data.get('user')} 於 {data.get('time')} 打卡成功"
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

    # ── Slots & Logic ────────────────────────────────────────

    def _on_card_scanned(self, uid: str):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info(f"[UI] 感應卡號: {uid}")

        worker = PunchWorker(uid, now, self.API_URL)
        self._setup_punch_signals()
        self.worker_manager.start(worker)

    def _trigger_retry(self):
        if not self.worker_manager.is_running(RetryWorker.WORKER_ID):
            worker = RetryWorker(self.API_URL)
            self._setup_retry_signals()
            self.worker_manager.start(worker)

    def _safe_exit(self):
        self.reader.stop()
        self.worker_manager.cancel_all()
        QApplication.quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    client = PunchClient()
    sys.exit(app.exec())
