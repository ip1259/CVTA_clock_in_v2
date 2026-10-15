import hmac
import json
import secrets
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api_server import app
from database.database_manager import db_manager
from device_protocol import request_signature, response_signature


class DeviceApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_engine, self.old_session = db_manager.hot_engine, db_manager.HotSession
        db_manager.hot_engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'test.db'}", connect_args={"check_same_thread": False})
        db_manager.HotSession = sessionmaker(bind=db_manager.hot_engine)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.device_uuid = str(uuid.uuid4())
        self.secret = secrets.token_hex(32)
        response = self.client.post("/api/v1/devices/register", json={"uuid": self.device_uuid,
                                      "secret": self.secret, "name": "Test Reader"})
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        db_manager.hot_engine.dispose()
        db_manager.hot_engine, db_manager.HotSession = self.old_engine, self.old_session
        self.temp.cleanup()

    def signed(self, method, path, data=None, nonce=None, signature=None, extra_headers=None):
        import time
        body = json.dumps(data, separators=(",", ":")).encode() if data is not None else b""
        nonce = nonce or secrets.token_hex(16)
        timestamp = str(int(time.time()))
        headers = {"Content-Type": "application/json", "X-Device-Id": self.device_uuid, "X-Device-Timestamp": timestamp,
                   "X-Device-Nonce": nonce,
                   "X-Device-Signature": signature or request_signature(self.secret, method, path, timestamp, nonce, body)}
        headers.update(extra_headers or {})
        response = self.client.request(method, path, content=body, headers=headers)
        expected = response_signature(self.secret, nonce, response.status_code, response.content)
        self.assertTrue(hmac.compare_digest(response.headers["X-Device-Response-Signature"], expected))
        return response

    def test_allowlist_replay_and_commands(self):
        from database.device_manager import DeviceManager
        punch = {"uid": "unknown", "timestamp": "2026-10-15 09:00:00"}
        self.assertEqual(self.signed("POST", "/api/v1/punch", punch).status_code, 403)
        DeviceManager.update(self.device_uuid, status="approved")
        self.assertEqual(self.signed("POST", "/api/v1/punch", punch).status_code, 404)
        self.assertNotEqual(self.signed("POST", "/api/v1/cards/empty", {"uid": "test-card"}).status_code, 200)
        login = self.client.post("/api/v1/login", json={"username": "admin", "password": "admin"})
        token = login.json()["access_token"]
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {"uid": "test-card"},
                                     extra_headers={"Authorization": f"Bearer {token}"}).status_code, 200)
        nonce = secrets.token_hex(16)
        self.assertEqual(self.signed("GET", "/api/v1/devices/me", nonce=nonce).status_code, 200)
        self.assertEqual(self.signed("GET", "/api/v1/devices/me", nonce=nonce).status_code, 401)
        self.assertEqual(self.signed("GET", "/api/v1/devices/me", signature="0" * 64).status_code, 401)
        DeviceManager.command(self.device_uuid, "pause")
        self.assertTrue(self.signed("GET", "/api/v1/devices/me").json()["paused"])
        self.assertEqual(self.signed("POST", "/api/v1/punch", punch).status_code, 403)
        DeviceManager.command(self.device_uuid, "resume")
        command = DeviceManager.command(self.device_uuid, "restart")
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{command['id']}/ack").status_code, 200)
        self.assertFalse(self.signed("GET", "/api/v1/devices/me").json()["commands"])
        DeviceManager.update(self.device_uuid, status="revoked")
        self.assertEqual(self.signed("POST", "/api/v1/punch", punch).status_code, 403)
        self.assertEqual(self.signed("GET", "/api/v1/devices/me").json()["status"], "revoked")


if __name__ == "__main__":
    unittest.main()
