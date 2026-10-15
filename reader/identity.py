"""Persistent desktop reader identity and server configuration."""
import json
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def default_server_url():
    base = os.getenv("CVTA_CLOCKIN_API_URL", "http://127.0.0.1").rstrip("/")
    port = os.getenv("CVTA_CLOCKIN_API_PORT", "16688")
    parsed = urlsplit(base)
    return base if parsed.port is not None else f"{base}:{port}"


class DeviceIdentity:
    def __init__(self, path=None):
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".cvta-clock-in") / "CVTAClockIn"
        self.path = Path(path) if path else root / "device.json"
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {"uuid": str(uuid.uuid4()), "secret": secrets.token_hex(32),
                    "server_url": default_server_url(), "name": os.getenv("COMPUTERNAME", "Reader")}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.uuid = data["uuid"]
        self.secret = data["secret"]
        self.server_url = data["server_url"].rstrip("/")
        self.name = data["name"]
        self.registered = bool(data.get("registered", False))

    def _save(self):
        data = {"uuid": self.uuid, "secret": self.secret, "server_url": self.server_url,
                "name": self.name, "registered": self.registered}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_registered(self):
        self.registered = True
        self._save()

    def set_server_url(self, url):
        self.server_url = url.rstrip("/")
        self.registered = False
        self._save()
