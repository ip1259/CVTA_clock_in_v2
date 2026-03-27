"""
worker_manager.py
=================
統一管理所有 BaseWorker 的生命週期。

功能：
- 啟動 / 取消 / 查詢 Worker 狀態
- 統一監聽所有 Worker 的訊號
- 避免同一 Worker 重複執行
"""

from __future__ import annotations
from typing import Callable

from PySide6.QtCore import QObject, Signal

from worker.worker_base import BaseWorker, WorkerSignals


class WorkerManager(QObject):
    """
    統一的 Worker 調度中心。

    用法::

        manager = WorkerManager()

        # 訂閱任意 worker 的事件
        manager.on_progress("llm_loader", lambda p, msg: print(p, msg))
        manager.on_success("llm_loader", lambda result: print(result))

        # 啟動
        manager.start(LLMWorker())
    """

    # 全域訊號（所有 worker 都會觸發）
    any_started = Signal(str)           # worker_id
    any_progress = Signal(str, int, str)  # worker_id, percent, message
    any_success = Signal(str, object)   # worker_id, result
    any_error = Signal(str, str)      # worker_id, error_message
    any_finished = Signal(str)           # worker_id

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._workers: dict[str, BaseWorker] = {}

    # ── 啟動 ─────────────────────────────────────────────────

    def start(self, worker: BaseWorker) -> bool:
        """
        啟動一個 Worker。
        若同 ID 的 Worker 正在執行則忽略並回傳 False。
        """
        wid = worker.WORKER_ID

        if wid in self._workers and self._workers[wid].isRunning():
            return False  # 已在執行中，忽略

        # 接通全域訊號
        s: WorkerSignals = worker.signals
        s.started.connect(self.any_started)
        s.progress.connect(self.any_progress)
        s.success.connect(self.any_success)
        s.error.connect(self.any_error)
        s.finished.connect(lambda wid=wid: self._on_finished(wid))

        self._workers[wid] = worker
        worker.start()
        return True

    # ── 取消 ─────────────────────────────────────────────────

    def cancel(self, worker_id: str) -> None:
        """請求取消指定 Worker"""
        if worker := self._workers.get(worker_id):
            worker.cancel()

    def cancel_all(self) -> None:
        for wid in list(self._workers):
            self.cancel(wid)

    # ── 查詢 ─────────────────────────────────────────────────

    def is_running(self, worker_id: str) -> bool:
        worker = self._workers.get(worker_id)
        return worker.isRunning() if worker else False

    def running_ids(self) -> list[str]:
        return [wid for wid, w in self._workers.items() if w.isRunning()]

    # ── 便利訂閱 API ──────────────────────────────────────────

    def on_progress(
        self,
        worker_id: str,
        callback: Callable[[int, str], None]
    ) -> None:
        """訂閱特定 worker 的進度訊號"""
        self.any_progress.connect(
            lambda wid, p, msg, _id=worker_id, _cb=callback:
                _cb(p, msg) if wid == _id else None
        )

    def on_success(
        self,
        worker_id: str,
        callback: Callable[[object], None]
    ) -> None:
        """訂閱特定 worker 的成功訊號"""
        self.any_success.connect(
            lambda wid, result, _id=worker_id, _cb=callback:
                _cb(result) if wid == _id else None
        )

    def on_error(
        self,
        worker_id: str,
        callback: Callable[[str], None]
    ) -> None:
        """訂閱特定 worker 的錯誤訊號"""
        self.any_error.connect(
            lambda wid, msg, _id=worker_id, _cb=callback:
                _cb(msg) if wid == _id else None
        )

    def on_finished(
        self,
        worker_id: str,
        callback: Callable[[], None]
    ) -> None:
        """訂閱特定 worker 完成訊號（成功或失敗都觸發）"""
        self.any_finished.connect(
            lambda wid, _id=worker_id, _cb=callback:
                _cb() if wid == _id else None
        )

    # ── 內部 ─────────────────────────────────────────────────

    def _on_finished(self, worker_id: str) -> None:
        self.any_finished.emit(worker_id)
        # 自動清理已完成的 worker
        if worker := self._workers.get(worker_id):
            worker.deleteLater()
            del self._workers[worker_id]
