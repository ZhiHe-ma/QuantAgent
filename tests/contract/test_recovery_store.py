import importlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

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

    def snapshot(self, *, store=None, run_id="run_fixture", date="2026-10-03"):
        owner = store or self.store
        payload = daily_payload(date)
        payload["audit_facts"]["run"]["run_id"] = run_id
        return self.r.freeze_snapshot(instance_id=owner.instance_id, run_id=run_id,
                                      kind="daily", date=date,
                                      created_at=date + "T08:00:00+08:00", payload=payload)

    @contextmanager
    def commit_before_read(self, predicate, commit):
        """Schedule a real independent commit; all SQL still runs in SQLite."""
        connect = sqlite3.connect
        fired = []

        class InterleavedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if not fired and predicate(sql, parameters):
                    fired.append(True)
                    commit()
                return super().execute(sql, parameters)

        def open_connection(database, *args, **kwargs):
            if str(database).endswith("?mode=ro"):
                kwargs["factory"] = InterleavedConnection
            return connect(database, *args, **kwargs)

        with patch.object(self.s.sqlite3, "connect", open_connection):
            yield
        self.assertEqual(fired, [True], "the interleaved commit was not exercised")

    def enable_wal(self, store):
        with closing(sqlite3.connect(store.db_path)) as connection:
            self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")

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
        # A failed read must release its default-mode locks for another writer.
        with closing(sqlite3.connect(db, timeout=0)) as connection:
            connection.execute("PRAGMA user_version=1")
            connection.commit()
        self.assertEqual(self.store.get(snap.run_id).snapshot, snap)

    def test_status_reads_use_one_snapshot_during_valid_event_commit(self):
        readers = (
            ("get", lambda store: store.get("run_fixture")),
            ("find_daily", lambda store: store.find_daily("2026-10-03")),
            ("list_open", lambda store: store.list_open()),
            ("filtered_list", lambda store: store.list_open("daily")),
            ("dry_run", lambda store: store.get("run_fixture")),
        )
        for name, read in readers:
            with self.subTest(reader=name):
                directory = self.root / name
                writer = self.s.SQLiteRecoveryStore(str(directory))
                writer.create(self.snapshot(store=writer))
                self.enable_wal(writer)
                reader = self.s.SQLiteRecoveryStore(str(directory), dry_run=name == "dry_run")
                event = self.c.RecoveryEvent("start", "report", "running", "2026-10-03T08:01:00+08:00", {})
                try:
                    with self.commit_before_read(
                            lambda sql, params: "FROM recovery_events" in sql,
                            lambda: writer.append_event("run_fixture", event, expected_revision=0)):
                        result = read(reader)
                except self.c.RecoveryInvalidState as exc:
                    self.fail(f"valid concurrent commit was reported as corruption: {exc}")
                records = result if isinstance(result, list) else [result]
                self.assertEqual(len(records), 1)
                self.assertEqual((records[0].revision, records[0].state, records[0].steps["report"],
                                  len(records[0].events)), (0, "pending", "pending", 0))
                latest = writer.get("run_fixture")
                self.assertEqual((latest.revision, latest.steps["report"], len(latest.events)), (1, "running", 1))
                # Actual corruption must still be rejected, never swallowed as a race.
                with closing(sqlite3.connect(writer.db_path)) as connection:
                    connection.execute("UPDATE execution_records SET revision=77 WHERE run_id='run_fixture'")
                    connection.commit()
                with self.assertRaises(self.c.RecoveryInvalidState):
                    read(reader)

    def test_list_open_does_not_mix_snapshots_between_records(self):
        self.store.create(self.snapshot())
        self.store.create(self.snapshot(run_id="run_second", date="2026-10-04"))
        self.enable_wal(self.store)

        def commit_both():
            for run_id, date in (("run_fixture", "2026-10-03"), ("run_second", "2026-10-04")):
                event = self.c.RecoveryEvent("start", "report", "running", date + "T08:01:00+08:00", {})
                self.store.append_event(run_id, event, expected_revision=0)

        with self.commit_before_read(
                lambda sql, params: "FROM execution_records" in sql and tuple(params) == ("run_second",),
                commit_both):
            records = self.store.list_open()
        self.assertEqual([(record.snapshot.run_id, record.revision) for record in records],
                         [("run_fixture", 0), ("run_second", 0)])
        self.assertEqual([(record.snapshot.run_id, record.revision) for record in self.store.list_open()],
                         [("run_fixture", 1), ("run_second", 1)])

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
