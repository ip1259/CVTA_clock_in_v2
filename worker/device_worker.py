import httpx
from device_protocol import signed_request
from worker.worker_base import BaseWorker


class DeviceSyncWorker(BaseWorker):
    WORKER_ID = "device_sync"

    def __init__(self, identity):
        super().__init__()
        self.identity = identity

    def execute(self):
        base = self.identity.server_url + "/api/v1/devices"
        registration_complete = False
        try:
            with httpx.Client(timeout=5.0) as client:
                if not self.identity.registered:
                    registration = client.post(base + "/register", json={
                        "uuid": self.identity.uuid, "secret": self.identity.secret, "name": self.identity.name})
                    if registration.status_code != 200:
                        return {"status": "registration_error", "message": registration.text}
                    registration_complete = True
                response = signed_request(client, "GET", base + "/me", self.identity.uuid, self.identity.secret)
                if response.status_code != 200:
                    return {"status": "registration_error", "message": response.text}
                state = response.json()
                state["registered"] = registration_complete
                for command in state.get("commands", []):
                    if command["kind"] == "restart":
                        ack = signed_request(client, "POST", base + f"/me/commands/{command['id']}/ack",
                                             self.identity.uuid, self.identity.secret)
                        if ack.status_code == 200:
                            state["restart"] = True
                return state
        except ValueError as exc:
            return {"status": "auth_error", "message": str(exc), "registered": registration_complete}
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            return {"status": "offline", "message": str(exc), "registered": registration_complete}
