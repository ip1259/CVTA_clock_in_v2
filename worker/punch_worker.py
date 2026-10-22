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
                    # A connection or signing failure affects the whole batch.
                    # Retrying every entry only repeats the same timeout.
                    break

        if success_items:
            self.mgr.remove_punches(success_items)
        return {"success_count": len(success_items)}


class AddCardWorker(BaseWorker):
    WORKER_ID = "add_card_task"

    def __init__(self, uid: str, api_url: str, credential: str, identity):
        super().__init__()
        self.uid = uid
        self.api_url = api_url
        self.credential = credential
        self.identity = identity

    def execute(self) -> dict:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = signed_request(client, "POST", self.api_url, self.identity.uuid,
                                      self.identity.secret,
                                      {"uid": self.uid, "credential": self.credential})
                if resp.status_code == 200:
                    return {"status": "success", "uid": self.uid}
                if resp.status_code == 400:
                    return {"status": "duplicate", "uid": self.uid}
                return {"status": "error", "uid": self.uid,
                        "message": f"伺服器拒絕新增（HTTP {resp.status_code}）"}
        except (httpx.TransportError, httpx.TimeoutException, ValueError):
            logger.warning("Add card response unavailable or invalid for UID %s", self.uid)
            return {"status": "unknown", "uid": self.uid}
