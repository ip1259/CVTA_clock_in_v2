import httpx
import logging
from device_protocol import signed_request
from worker.worker_base import BaseWorker
from worker.offline_manager import OfflineManager

logger = logging.getLogger(__name__)


class PunchWorker(BaseWorker):
    WORKER_ID = "punch_task"

    def __init__(self, uid: str, timestamp: str, api_url: str, identity):
        super().__init__()
        self.uid = uid
        self.timestamp = timestamp
        self.api_url = api_url
        self.identity = identity

    def execute(self) -> dict:
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = signed_request(client, "POST", self.api_url, self.identity.uuid, self.identity.secret, {
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
                if resp.status_code >= 500:
                    return {"status": "offline", "uid": self.uid, "timestamp": self.timestamp}
                return {"status": "error", "uid": self.uid, "message": resp.json().get("detail", f"HTTP {resp.status_code}")}
        except (httpx.TransportError, httpx.TimeoutException):
            return {"status": "offline", "uid": self.uid,
                    "timestamp": self.timestamp}
        except ValueError as exc:
            return {"status": "error", "uid": self.uid, "message": str(exc)}


class RetryWorker(BaseWorker):
    WORKER_ID = "retry_task"

    def __init__(self, api_url: str, identity):
        super().__init__()
        self.api_url = api_url
        self.identity = identity
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
                    if item.get("device_uuid") != self.identity.uuid:
                        continue
                    resp = signed_request(client, "POST", self.api_url, self.identity.uuid,
                                          self.identity.secret, {"uid": item["uid"], "timestamp": item["timestamp"]})
                    if resp.status_code == 200:
                        success_items.append(item)
                    elif resp.status_code in (401, 403):
                        break
                except (httpx.TransportError, httpx.TimeoutException, ValueError):
                    continue

        if success_items:
            self.mgr.remove_punches(success_items)
        return {"success_count": len(success_items)}


class AddCardWorker(BaseWorker):
    WORKER_ID = "add_card_task"

    def __init__(self, uid: str, api_url: str, token: str, identity):
        super().__init__()
        self.uid = uid
        self.api_url = api_url
        self.token = token
        self.identity = identity

    def execute(self) -> dict:
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            with httpx.Client(timeout=5.0) as client:
                resp = signed_request(client, "POST", self.api_url, self.identity.uuid,
                                      self.identity.secret, {"uid": self.uid}, headers=headers)
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
            logger.exception("Add Card Task Error")
            return {"status": "error", "message": str(e)}
