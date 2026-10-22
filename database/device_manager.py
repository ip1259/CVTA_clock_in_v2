"""Reader registration, allowlist, replay protection, and remote commands."""
from datetime import timedelta
import hmac
import secrets
from sqlalchemy.exc import IntegrityError
from database.database_manager import db_manager
from database.base import ReaderDevice, DeviceNonce, DeviceCommand, Card, utcnow_naive


def device_view(device):
    return {"uuid": device.uuid, "name": device.name, "status": device.status,
            "paused": device.paused, "last_seen": device.last_seen.isoformat() if device.last_seen else None,
            "created_at": device.created_at.isoformat() if device.created_at else None}


class DeviceManager:
    @staticmethod
    def register(device_uuid, secret, name):
        with db_manager.HotSession.begin() as session:
            device = session.get(ReaderDevice, device_uuid)
            if device:
                if device.secret != secret:
                    return None
                return device_view(device)
            device = ReaderDevice(uuid=device_uuid, secret=secret, name=name[:100], status="pending")
            session.add(device)
            session.flush()
            return device_view(device)

    @staticmethod
    def list_all():
        with db_manager.HotSession() as session:
            return [device_view(d) for d in session.query(ReaderDevice).order_by(ReaderDevice.created_at.desc()).all()]

    @staticmethod
    def get_secret(device_uuid):
        with db_manager.HotSession() as session:
            device = session.get(ReaderDevice, device_uuid)
            return (device.secret, device.status) if device else None

    @staticmethod
    def consume_nonce(device_uuid, nonce):
        now = utcnow_naive()
        try:
            with db_manager.HotSession.begin() as session:
                session.query(DeviceNonce).filter(DeviceNonce.expires_at < now).delete(synchronize_session=False)
                session.add(DeviceNonce(device_uuid=device_uuid, nonce=nonce, expires_at=now + timedelta(minutes=10)))
                session.flush()
                device = session.get(ReaderDevice, device_uuid)
                device.last_seen = now
            return True
        except IntegrityError:
            return False

    @staticmethod
    def update(device_uuid, *, name=None, status=None):
        with db_manager.HotSession.begin() as session:
            device = session.get(ReaderDevice, device_uuid)
            if not device:
                return None
            if name is not None:
                device.name = name[:100]
            if status is not None:
                if device.status == "revoked" and status != "revoked":
                    raise ValueError("Revoked device cannot be reactivated")
                device.status = status
                if status != "approved":
                    session.query(DeviceCommand).filter(
                        DeviceCommand.device_uuid == device_uuid,
                        (DeviceCommand.acknowledged_at.is_(None)) |
                        ((DeviceCommand.kind == "enroll_card") & (DeviceCommand.consumed_at.is_(None)))).update(
                            {DeviceCommand.expires_at: utcnow_naive()}, synchronize_session=False)
            session.flush()
            return device_view(device)

    @staticmethod
    def command(device_uuid, kind):
        with db_manager.HotSession.begin() as session:
            device = session.get(ReaderDevice, device_uuid)
            if not device or device.status != "approved":
                return None
            if kind == "pause":
                device.paused = True
                session.query(DeviceCommand).filter(
                    DeviceCommand.device_uuid == device_uuid,
                    DeviceCommand.kind == "enroll_card",
                    DeviceCommand.consumed_at.is_(None)).update(
                        {DeviceCommand.expires_at: utcnow_naive()}, synchronize_session=False)
            elif kind == "resume":
                device.paused = False
            elif kind in ("restart", "enroll_card"):
                if kind == "enroll_card" and device.paused:
                    return None
                if kind == "enroll_card":
                    session.query(DeviceCommand).filter(
                        DeviceCommand.device_uuid == device_uuid,
                        DeviceCommand.kind == "enroll_card",
                        DeviceCommand.consumed_at.is_(None)).update(
                            {DeviceCommand.expires_at: utcnow_naive()}, synchronize_session=False)
                command = DeviceCommand(device_uuid=device_uuid, kind=kind,
                                        expires_at=utcnow_naive() + timedelta(minutes=5),
                                        token=secrets.token_hex(32) if kind == "enroll_card" else None)
                session.add(command)
                session.flush()
                return {"id": command.id, "kind": kind}
            else:
                raise ValueError("Unknown command")
            return {"kind": kind}

    @staticmethod
    def poll(device_uuid):
        with db_manager.HotSession() as session:
            device = session.get(ReaderDevice, device_uuid)
            if not device:
                return None
            commands = []
            if device.status == "approved" and not device.paused:
                commands = session.query(DeviceCommand).filter(
                    DeviceCommand.device_uuid == device_uuid,
                    DeviceCommand.acknowledged_at.is_(None),
                    DeviceCommand.expires_at > utcnow_naive()
                ).order_by(DeviceCommand.id).all()
            return {"status": device.status, "paused": device.paused,
                    "commands": [{"id": c.id, "kind": c.kind,
                                  **({"credential": c.token} if c.kind == "enroll_card" else {})}
                                 for c in commands]}

    @staticmethod
    def acknowledge(device_uuid, command_id):
        with db_manager.HotSession.begin() as session:
            command = session.get(DeviceCommand, command_id)
            if not command or command.device_uuid != device_uuid or command.expires_at < utcnow_naive():
                return False
            if command.kind == "enroll_card":
                if not DeviceManager._active_in_session(session, device_uuid):
                    return False
                if command.acknowledged_at is not None:
                    return False
                command.expires_at = utcnow_naive() + timedelta(seconds=30)
            command.acknowledged_at = command.acknowledged_at or utcnow_naive()
            return True

    @staticmethod
    def enrollment_result(device_uuid, command_id):
        with db_manager.HotSession() as session:
            command = session.get(DeviceCommand, command_id)
            if not command or command.device_uuid != device_uuid or command.kind != "enroll_card":
                return None
            if command.result_code == "created":
                status = "succeeded"
            elif command.result_code == "duplicate":
                status = "duplicate"
            elif command.expires_at <= utcnow_naive():
                status = "expired"
            elif command.acknowledged_at is not None:
                status = "waiting_for_card"
            else:
                status = "pending_delivery"
            return {"id": command.id, "status": status, "uid": command.result_uid,
                    "expires_at": command.expires_at.isoformat()}

    @staticmethod
    def is_active(device_uuid):
        with db_manager.HotSession() as session:
            device = session.get(ReaderDevice, device_uuid)
            return bool(device and device.status == "approved" and not device.paused)

    @staticmethod
    def _active_in_session(session, device_uuid):
        device = session.get(ReaderDevice, device_uuid)
        return bool(device and device.status == "approved" and not device.paused)

    @staticmethod
    def add_card_once(device_uuid, credential, uid):
        if not isinstance(credential, str) or len(credential) != 64 or not uid:
            return False, "加卡憑證無效"
        session = db_manager.HotSession()
        try:
            # Serialize token consumption and card insertion on SQLite.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            if not DeviceManager._active_in_session(session, device_uuid):
                session.rollback()
                return False, "裝置未啟用"
            now = utcnow_naive()
            command = session.query(DeviceCommand).filter(
                DeviceCommand.device_uuid == device_uuid,
                DeviceCommand.kind == "enroll_card",
                DeviceCommand.acknowledged_at.is_not(None),
                DeviceCommand.consumed_at.is_(None),
                DeviceCommand.expires_at > now).order_by(DeviceCommand.id.desc()).first()
            if not command or not hmac.compare_digest(command.token or "", credential):
                session.rollback()
                return False, "加卡憑證無效或已過期"
            command.consumed_at = now
            exists = session.query(Card).filter(Card.uid == uid).first() is not None
            command.result_code = "duplicate" if exists else "created"
            command.result_uid = uid
            if not exists:
                session.add(Card(uid=uid, employee_id=None))
            session.commit()
            return (False, "卡號已存在") if exists else (True, "成功新增空卡")
        except IntegrityError:
            session.rollback()
            return False, "卡號已存在"
        finally:
            session.close()
