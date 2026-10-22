import hmac
import json
import secrets
import tempfile
import unittest
import uuid
from datetime import timedelta
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
        self.assertNotEqual(self.signed("POST", "/api/v1/cards/empty", {"uid": "test-card"},
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

    def test_one_time_enrollment(self):
        from database.device_manager import DeviceManager
        from database.base import Card, Record
        DeviceManager.update(self.device_uuid, status="approved")
        self.assertNotEqual(self.client.post(f"/api/v1/devices/{self.device_uuid}/commands",
                                             json={"kind": "enroll_card"}).status_code, 200)
        login = self.client.post("/api/v1/login", json={"username": "admin", "password": "admin"})
        token = login.json()["access_token"]
        response = self.client.post(f"/api/v1/devices/{self.device_uuid}/commands",
                                    json={"kind": "enroll_card"},
                                    headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        status_path = f"/api/v1/devices/{self.device_uuid}/commands/{response.json()['id']}"
        self.assertEqual(self.client.get(status_path).status_code, 401)
        self.assertEqual(self.client.get(
            f"/api/v1/devices/{uuid.uuid4()}/commands/{response.json()['id']}",
            headers={"Authorization": f"Bearer {token}"}).status_code, 404)
        self.assertEqual(self.client.get(status_path, headers={"Authorization": f"Bearer {token}"}).json()["status"],
                         "pending_delivery")
        command = self.signed("GET", "/api/v1/devices/me").json()["commands"][0]
        credential = command["credential"]
        payload = {"uid": "ABCDEF12", "credential": credential}
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", payload).status_code, 403)
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{command['id']}/ack").status_code, 200)
        self.assertEqual(self.client.get(status_path, headers={"Authorization": f"Bearer {token}"}).json()["status"],
                         "waiting_for_card")
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", payload, signature="0" * 64).status_code, 401)
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", payload).status_code, 200)
        result = self.client.get(status_path, headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual((result["status"], result["uid"]), ("succeeded", "ABCDEF12"))
        self.assertNotIn("credential", result)
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", payload).status_code, 403)
        with db_manager.HotSession() as session:
            self.assertEqual(session.query(Card).filter_by(uid="ABCDEF12").count(), 1)
            self.assertEqual(session.query(Record).count(), 0)

        second = DeviceManager.command(self.device_uuid, "enroll_card")
        new_credential = self.signed("GET", "/api/v1/devices/me").json()["commands"][0]["credential"]
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{second['id']}/ack").status_code, 200)
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty",
                                     {"uid": "ABCDEF12", "credential": new_credential}).status_code, 400)
        duplicate = self.client.get(
            f"/api/v1/devices/{self.device_uuid}/commands/{second['id']}",
            headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual((duplicate["status"], duplicate["uid"]), ("duplicate", "ABCDEF12"))
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty",
                                     {"uid": "OTHER", "credential": new_credential}).status_code, 403)

    def test_enrollment_expires_and_is_bound_to_device_state(self):
        from database.device_manager import DeviceManager
        from database.base import DeviceCommand, utcnow_naive
        DeviceManager.update(self.device_uuid, status="approved")
        command = DeviceManager.command(self.device_uuid, "enroll_card")
        credential = self.signed("GET", "/api/v1/devices/me").json()["commands"][0]["credential"]
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{command['id']}/ack").status_code, 200)

        other_uuid, other_secret = str(uuid.uuid4()), secrets.token_hex(32)
        self.assertEqual(self.client.post("/api/v1/devices/register", json={
            "uuid": other_uuid, "secret": other_secret, "name": "Other"}).status_code, 200)
        DeviceManager.update(other_uuid, status="approved")
        original_uuid, original_secret = self.device_uuid, self.secret
        self.device_uuid, self.secret = other_uuid, other_secret
        try:
            self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {
                "uid": "WRONG", "credential": credential}).status_code, 403)
        finally:
            self.device_uuid, self.secret = original_uuid, original_secret

        with db_manager.HotSession.begin() as session:
            session.get(DeviceCommand, command["id"]).expires_at = utcnow_naive() - timedelta(seconds=1)
        token = self.client.post("/api/v1/login", json={"username": "admin", "password": "admin"}).json()["access_token"]
        expired = self.client.get(
            f"/api/v1/devices/{self.device_uuid}/commands/{command['id']}",
            headers={"Authorization": f"Bearer {token}"}).json()
        self.assertEqual(expired["status"], "expired")
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {
            "uid": "LATE", "credential": credential}).status_code, 403)

        paused = DeviceManager.command(self.device_uuid, "enroll_card")
        paused_credential = self.signed("GET", "/api/v1/devices/me").json()["commands"][0]["credential"]
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{paused['id']}/ack").status_code, 200)
        DeviceManager.command(self.device_uuid, "pause")
        self.assertIsNone(DeviceManager.command(self.device_uuid, "enroll_card"))
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {
            "uid": "PAUSED", "credential": paused_credential}).status_code, 403)
        DeviceManager.command(self.device_uuid, "resume")
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {
            "uid": "PAUSED", "credential": paused_credential}).status_code, 403)

        revoked = DeviceManager.command(self.device_uuid, "enroll_card")
        revoked_credential = self.signed("GET", "/api/v1/devices/me").json()["commands"][0]["credential"]
        self.assertEqual(self.signed("POST", f"/api/v1/devices/me/commands/{revoked['id']}/ack").status_code, 200)
        DeviceManager.update(self.device_uuid, status="revoked")
        self.assertEqual(self.signed("POST", "/api/v1/cards/empty", {
            "uid": "REVOKED", "credential": revoked_credential}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
