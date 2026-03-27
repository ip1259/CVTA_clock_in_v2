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
                    data = resp.json()
                    return {
                        "status": "online",
                        "uid": self.uid,
                        "employee_name": data.get("employee_name", self.uid),
                        "timestamp": self.timestamp,
                        "data": data
                    }
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


class AddCardWorker(BaseWorker):
    WORKER_ID = "add_card_task"

    def __init__(self, uid: str, api_url: str, token: str):
        super().__init__()
        self.uid = uid
        self.api_url = api_url
        self.token = token

    def execute(self) -> dict:
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(self.api_url, json={
                                   "uid": self.uid}, headers=headers)
                if resp.status_code == 200:
                    return {"status": "success", "uid": self.uid}

                # 修正：防禦性解析 JSON，避免 404 HTML 導致解析崩潰
                try:
                    error_detail = resp.json().get(
                        "detail", f"錯誤代碼: {resp.status_code}")
                except Exception:
                    # 如果不是 JSON 格式 (例如 404 HTML 頁面)，則抓取 HTTP 狀態原因
                    error_detail = f"伺服器錯誤 ({resp.status_code}): {resp.reason_phrase}"

                return {"status": "error", "message": error_detail}
        except Exception as e:
            logger.error(f"Add Card Task Error: {e}")
            return {"status": "error", "message": str(e)}
