import httpx
import logging
from worker.worker_base import BaseWorker
from worker.offline_manager import OfflineManager

logger = logging.getLogger(__name__)


class PunchWorker(BaseWorker):
    WORKER_ID = "punch_task"

    def __init__(self, uid: str, timestamp: str, api_url: str):
        super().__init__()
        self.uid = uid
        self.timestamp = timestamp
        self.api_url = api_url

    def execute(self) -> dict:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(self.api_url, json={
                    "uid": self.uid,
                    "timestamp": self.timestamp
                })
                if resp.status_code == 200:
                    return {"status": "online", "data": resp.json()}
                raise Exception("Server Error")
        except Exception:
            return {"status": "offline", "uid": self.uid,
                    "timestamp": self.timestamp}


class RetryWorker(BaseWorker):
    WORKER_ID = "retry_task"

    def __init__(self, api_url: str):
        super().__init__()
        self.api_url = api_url
        self.mgr = OfflineManager()

    def execute(self) -> dict:
        pending = self.mgr.load_all()
        if not pending:
            return {"success_count": 0}

        success_items = []
        with httpx.Client(timeout=5.0) as client:
            for item in pending:
                if self.is_cancelled:
                    break
                try:
                    resp = client.post(self.api_url, json=item)
                    if resp.status_code == 200:
                        success_items.append(item)
                except Exception:
                    continue

        if success_items:
            self.mgr.remove_punches(success_items)
        return {"success_count": len(success_items)}
