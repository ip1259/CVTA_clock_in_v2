"""
worker_base.py
==============
所有背景工作的抽象基類。
繼承 BaseWorker 並實作 run() 即可新增新的耗時工作。
"""

from __future__ import annotations
from abc import abstractmethod
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal


# ── Signals 容器（QObject 才能持有 Signal）──────────────────────
class WorkerSignals(QObject):
    """所有 Worker 共用的訊號定義"""
    started = Signal(str)          # worker_id
    progress = Signal(str, int, str)  # worker_id, percent(0-100), message
    success = Signal(str, object)  # worker_id, result
    error = Signal(str, str)     # worker_id, error_message
    finished = Signal(str)          # worker_id（無論成功或失敗都會發）


# ── 抽象 Worker ────────────────────────────────────────────────
class BaseWorker(QThread):
    """
    所有背景工作的基類。

    子類只需：
    1. 定義 WORKER_ID（唯一名稱）
    2. 實作 execute() 並在其中呼叫 self.report_progress()
    3. execute() 回傳的值會透過 signals.success 傳出

    範例::

        class MyWorker(BaseWorker):
            WORKER_ID = "my_task"

            def execute(self) -> Any:
                self.report_progress(50, "halfway done")
                return {"done": True}
    """

    WORKER_ID: str = "base_worker"

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.signals = WorkerSignals()
        self._cancelled = False

    # ── 公開 API ──────────────────────────────────────────────

    def report_progress(self, percent: int, message: str = "") -> None:
        """在 execute() 中呼叫，通知進度（0-100）"""
        self.signals.progress.emit(self.WORKER_ID, percent, message)

    def cancel(self) -> None:
        """請求取消（子類在 execute() 中應定期檢查 self.is_cancelled）"""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    # ── 子類實作 ──────────────────────────────────────────────

    @abstractmethod
    def execute(self) -> Any:
        """耗時工作的主體邏輯，在背景執行緒中被呼叫。"""
        ...

    # ── QThread 進入點（不要覆寫）────────────────────────────

    def run(self) -> None:
        self.signals.started.emit(self.WORKER_ID)
        try:
            result = self.execute()
            if not self._cancelled:
                self.signals.success.emit(self.WORKER_ID, result)
        except Exception as exc:
            self.signals.error.emit(self.WORKER_ID, str(exc))
        finally:
            self.signals.finished.emit(self.WORKER_ID)
