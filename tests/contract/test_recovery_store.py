import importlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from tests.support.paths import ROOT
from tests.support.recovery_fixtures import daily_payload


class RecoveryStoreTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "quantagent_platform/recovery/sqlite_store.py").is_file(),
                        "missing owned recovery storage")
        self.c = importlib.import_module("quantagent_platform.recovery.contracts")
        self.r = importlib.import_module("quantagent_platform.recovery.rules")
        self.s = importlib.import_module("quantagent_platform.recovery.sqlite_store")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "daily"
        self.store = self.s.SQLiteRecoveryStore(str(self.root))

    def snapshot(self):
        return self.r.freeze_snapshot(instance_id=self.store.instance_id, run_id="run_fixture",
                                      kind="daily", date="2026-10-03",
                                      created_at="2026-10-03T08:00:00+08:00", payload=daily_payload())

    def test_constructor_and_status_do_not_create_storage(self):
        self.assertIsNone(self.store.get("missing"))
        self.assertIsNone(self.store.find_daily("2026-10-03"))
        self.assertEqual(self.store.list_open(), [])
        self.assertFalse(self.root.exists())
        dry = self.s.SQLiteRecoveryStore(str(self.root), dry_run=True)
        with self.assertRaises(self.c.RecoveryInvalidState):
            dry.create(self.snapshot())
        self.assertFalse(self.root.exists())

    def test_invalid_version_hash_and_instance_are_rejected(self):
        snap = self.snapshot()
        for bad in (replace(snap, version=2), replace(snap, sha256="0" * 64),
                    replace(snap, instance_id="foreign")):
            with self.subTest(snapshot=bad), self.assertRaises(self.c.RecoveryInvalidState):
                self.store.create(bad)
        self.assertFalse(self.root.exists())
        self.store.create(snap)
        self.assertEqual(self.store.get(snap.run_id).snapshot, snap)
        db = self.root / "quantagent_recovery.sqlite3"
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("PRAGMA user_version=2")
        before = db.read_bytes()
        with self.assertRaises(self.c.RecoveryInvalidState):
            self.store.get(snap.run_id)
        self.assertEqual(db.read_bytes(), before)

    def test_event_append_is_atomic_and_revision_checked(self):
        record = self.store.create(self.snapshot())
        event = self.c.RecoveryEvent("start", "report", "running", "2026-10-03T08:01:00+08:00", {})
        updated = self.store.append_event(record.snapshot.run_id, event, expected_revision=0)
        self.assertEqual(updated.revision, 1)
        self.assertEqual(updated.steps["report"], "running")
        self.assertEqual(self.store.get(record.snapshot.run_id), updated)
        self.assertEqual(self.store.append_event(record.snapshot.run_id, event, expected_revision=0), updated)
        with self.assertRaises(self.c.RecoveryConflict):
            self.store.append_event(record.snapshot.run_id, replace(event, status="succeeded"), expected_revision=1)
        with self.assertRaises(self.c.RecoveryConflict):
            self.store.append_event(record.snapshot.run_id, replace(event, event_id="next"), expected_revision=0)
        self.assertEqual(len(self.store.get(record.snapshot.run_id).events), 1)

    def test_copied_database_cannot_be_adopted_by_another_instance(self):
        self.store.create(self.snapshot())
        foreign = Path(self.temp.name) / "foreign"
        foreign.mkdir()
        db = foreign / "quantagent_recovery.sqlite3"
        shutil.copyfile(self.root / db.name, db)
        before = db.read_bytes()
        with self.assertRaises(self.c.RecoveryInvalidState):
            self.s.SQLiteRecoveryStore(str(foreign)).list_open()
        self.assertEqual(db.read_bytes(), before)

    def test_execution_and_projection_locks_are_scoped(self):
        other = self.s.SQLiteRecoveryStore(str(self.root))
        with self.store.lock("daily"):
            with other.lock("monitor"):
                with self.assertRaises(self.c.RecoveryBusy):
                    with other.lock("daily"):
                        pass
            with self.store.lock("projection"):
                with self.store.lock("projection"):
                    with self.assertRaises(self.c.RecoveryBusy):
                        with other.lock("projection"):
                            pass
        with other.lock("daily"):
            pass
