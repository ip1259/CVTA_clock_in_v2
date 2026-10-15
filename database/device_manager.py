"""Reader registration, allowlist, replay protection, and remote commands."""
from datetime import timedelta
from sqlalchemy.exc import IntegrityError
from database.database_manager import db_manager
from database.base import ReaderDevice, DeviceNonce, DeviceCommand, utcnow_naive


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
                        DeviceCommand.acknowledged_at.is_(None)).update(
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
            elif kind == "resume":
                device.paused = False
            elif kind == "restart":
                command = DeviceCommand(device_uuid=device_uuid, kind=kind,
                                        expires_at=utcnow_naive() + timedelta(minutes=5))
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
            if device.status == "approved":
                commands = session.query(DeviceCommand).filter(
                    DeviceCommand.device_uuid == device_uuid,
                    DeviceCommand.acknowledged_at.is_(None),
                    DeviceCommand.expires_at > utcnow_naive()
                ).order_by(DeviceCommand.id).all()
            return {"status": device.status, "paused": device.paused,
                    "commands": [{"id": c.id, "kind": c.kind} for c in commands]}

    @staticmethod
    def acknowledge(device_uuid, command_id):
        with db_manager.HotSession.begin() as session:
            command = session.get(DeviceCommand, command_id)
            if not command or command.device_uuid != device_uuid or command.expires_at < utcnow_naive():
                return False
            command.acknowledged_at = command.acknowledged_at or utcnow_naive()
            return True

    @staticmethod
    def is_active(device_uuid):
        with db_manager.HotSession() as session:
            device = session.get(ReaderDevice, device_uuid)
            return bool(device and device.status == "approved" and not device.paused)
