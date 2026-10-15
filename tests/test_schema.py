import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from sqlalchemy import create_engine, text

from database.base import Base, ReaderDevice, DeviceNonce, DeviceCommand
from database.schema import migrate_hot_schema
from database.database_manager import DatabaseManager


class SchemaTests(unittest.TestCase):
    def test_failed_migration_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'failed.db'}")
            def fail_after_ddl(connection, **_kwargs):
                connection.exec_driver_sql("CREATE TABLE partial (id INTEGER)")
                raise RuntimeError("simulated DDL failure")
            with patch.object(Base.metadata, "create_all", side_effect=fail_after_ddl):
                with self.assertRaisesRegex(RuntimeError, "simulated"):
                    migrate_hot_schema(engine)
            with engine.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("PRAGMA user_version").scalar(), 0)
                self.assertIsNone(conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='partial'").first())
            engine.dispose()

    def test_archive_excludes_device_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = DatabaseManager(str(Path(directory) / "hot.db"))
            manager.archive_dir = directory
            session = manager.get_session(2001)
            try:
                tables = {name for (name,) in session.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
                self.assertIn("records", tables)
                self.assertNotIn("reader_devices", tables)
                self.assertNotIn("device_commands", tables)
            finally:
                session.close()
                for factory in manager._archive_engines.values():
                    factory.kw["bind"].dispose()
                manager.hot_engine.dispose()

    def test_v0_upgrade_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'hot.db'}")
            old_tables = [t for t in Base.metadata.sorted_tables if t not in
                          (ReaderDevice.__table__, DeviceNonce.__table__, DeviceCommand.__table__)]
            Base.metadata.create_all(engine, tables=old_tables)
            with engine.begin() as conn:
                conn.execute(text("INSERT INTO accounts (username, password_hash) VALUES ('keeper', 'hash')"))
            migrate_hot_schema(engine)
            migrate_hot_schema(engine)
            with engine.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("PRAGMA user_version").scalar(), 1)
                self.assertEqual(conn.execute(text("SELECT username FROM accounts")).scalar(), "keeper")
            engine.dispose()

    def test_fresh_unknown_and_future(self):
        with tempfile.TemporaryDirectory() as directory:
            fresh = create_engine(f"sqlite:///{Path(directory) / 'fresh.db'}")
            migrate_hot_schema(fresh)
            with fresh.connect() as conn:
                self.assertEqual(conn.exec_driver_sql("PRAGMA user_version").scalar(), 1)
            fresh.dispose()
            unknown = create_engine(f"sqlite:///{Path(directory) / 'unknown.db'}")
            with unknown.begin() as conn:
                conn.exec_driver_sql("CREATE TABLE odd (id INTEGER)")
            with self.assertRaises(RuntimeError):
                migrate_hot_schema(unknown)
            unknown.dispose()
            future = create_engine(f"sqlite:///{Path(directory) / 'future.db'}")
            with future.begin() as conn:
                conn.exec_driver_sql("PRAGMA user_version = 2")
            with self.assertRaises(RuntimeError):
                migrate_hot_schema(future)
            future.dispose()


if __name__ == "__main__":
    unittest.main()
