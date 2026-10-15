"""Versioned SQLite schema for the hot database."""
from sqlalchemy import inspect
from database.base import Base, ReaderDevice, DeviceNonce, DeviceCommand

SCHEMA_VERSION = 1
DEVICE_TABLES = (ReaderDevice.__table__, DeviceNonce.__table__, DeviceCommand.__table__)
BASELINE = {
    "accounts": {"id", "username", "password_hash"},
    "employees": {"id", "name", "nickname", "is_active", "schedule_id"},
    "cards": {"id", "uid", "employee_id"},
    "records": {"id", "uid", "employee_id", "record_time", "note"},
    "schedules": {"id", "name", "job_start", "job_end"},
    "holidays": {"id", "date", "is_workday", "description"},
    "shift_assignments": {"id", "employee_id", "schedule_id", "date"},
}


def _check_columns(connection, expected, exact=False):
    inspector = inspect(connection)
    actual = set(inspector.get_table_names())
    if (exact and actual != set(expected)) or (not exact and not set(expected).issubset(actual)):
        raise RuntimeError(f"Unknown database schema; table mismatch: {sorted(actual ^ set(expected))}")
    for table, columns in expected.items():
        present = {c["name"] for c in inspector.get_columns(table)}
        if (exact and present != columns) or (not exact and not columns.issubset(present)):
            raise RuntimeError(f"Unknown database schema; {table} column mismatch: {sorted(columns ^ present)}")


def migrate_hot_schema(engine):
    """Upgrade a known v0 database, or create a fresh v1 database atomically."""
    with engine.connect() as connection:
        version = connection.exec_driver_sql("PRAGMA user_version").scalar()
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"Database version {version} is newer than supported {SCHEMA_VERSION}")
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(f"Unsupported database version {version}")
        tables = set(inspect(connection).get_table_names())
        if version == SCHEMA_VERSION:
            _check_columns(connection, BASELINE)
            _check_columns(connection, {t.name: {c.name for c in t.columns} for t in DEVICE_TABLES})
            return
        if tables:
            _check_columns(connection, BASELINE, exact=True)
            if any(t.name in tables for t in DEVICE_TABLES):
                raise RuntimeError("Unversioned database contains device tables; manual recovery required")
        try:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if not tables:
                Base.metadata.create_all(connection)
            else:
                Base.metadata.create_all(connection, tables=DEVICE_TABLES)
            connection.exec_driver_sql(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
