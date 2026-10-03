"""Lazy, instance-bound SQLite journal and cooperative process locks."""
import hashlib
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .contracts import (SCHEMA_VERSION, ExecutionRecord, FrozenSnapshot, RecoveryBusy,
                        RecoveryConflict, RecoveryError, RecoveryEvent, RecoveryInvalidState, TaskKind)
from .rules import canonical_json, decode_json, initial_record, transition, validate_snapshot


class SQLiteRecoveryStore:
    def __init__(self, daily_dir: str, *, dry_run: bool = False):
        self.directory = Path(os.path.abspath(daily_dir))
        self.db_path = self.directory / "quantagent_recovery.sqlite3"
        self.instance_id = hashlib.sha256(os.path.normcase(str(self.directory)).encode("utf-8")).hexdigest()
        self.dry_run = bool(dry_run)
        self._locks = {}
        self._mutex = threading.RLock()

    def _check_schema(self, connection):
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            raise RecoveryInvalidState("unsupported recovery database version")
        foreign = connection.execute("SELECT 1 FROM execution_records WHERE instance_id != ? LIMIT 1", (self.instance_id,)).fetchone()
        if foreign:
            raise RecoveryInvalidState("recovery database belongs to another instance")

    @contextmanager
    def _connection(self, *, write=False):
        if write and self.dry_run:
            raise RecoveryInvalidState("dry-run prevents recovery mutation")
        if write:
            self.directory.mkdir(parents=True, exist_ok=True)
        connection = None
        try:
            connection = sqlite3.connect(self.db_path.as_uri() + ("?mode=rwc" if write else "?mode=ro"),
                                         uri=True, timeout=5, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if version == 0 and not tables:
                    connection.execute("""CREATE TABLE execution_records(
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE,
                        instance_id TEXT NOT NULL, snapshot_json TEXT NOT NULL, kind TEXT NOT NULL,
                        date TEXT NOT NULL, state TEXT NOT NULL, revision INTEGER NOT NULL, steps_json TEXT NOT NULL)""")
                    connection.execute("""CREATE TABLE recovery_events(
                        run_id TEXT NOT NULL REFERENCES execution_records(run_id), event_id TEXT NOT NULL,
                        revision INTEGER NOT NULL, event_json TEXT NOT NULL,
                        PRIMARY KEY(run_id,event_id), UNIQUE(run_id,revision))""")
                    connection.execute("PRAGMA user_version=1")
            self._check_schema(connection)
            yield connection
            if write:
                connection.commit()
        except sqlite3.Error as exc:
            raise RecoveryError("recovery database operation failed") from exc
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    def _load(self, connection, run_id):
        row = connection.execute("SELECT * FROM execution_records WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            return None
        try:
            snapshot = FrozenSnapshot(**decode_json(row["snapshot_json"]))
            validate_snapshot(snapshot)
            if snapshot.instance_id != self.instance_id or snapshot.run_id != row["run_id"] or snapshot.kind != row["kind"] or snapshot.date != row["date"]:
                raise RecoveryInvalidState("snapshot index mismatch")
            record = initial_record(snapshot)
            for stored in connection.execute("SELECT * FROM recovery_events WHERE run_id=? ORDER BY revision", (run_id,)):
                event = RecoveryEvent(**decode_json(stored["event_json"]))
                if stored["revision"] != record.revision + 1 or event.event_id != stored["event_id"]:
                    raise RecoveryInvalidState("event sequence mismatch")
                record = transition(record, event)
            if record.revision != row["revision"] or record.state != row["state"] or record.steps != decode_json(row["steps_json"]):
                raise RecoveryInvalidState("journal projection mismatch")
            return record
        except (TypeError, KeyError, ValueError) as exc:
            raise RecoveryInvalidState("malformed recovery record") from exc

    def get(self, run_id: str) -> ExecutionRecord | None:
        if not self.db_path.exists():
            return None
        with self._connection() as connection:
            return self._load(connection, run_id)

    def find_daily(self, date: str) -> ExecutionRecord | None:
        if not self.db_path.exists():
            return None
        with self._connection() as connection:
            row = connection.execute("SELECT run_id FROM execution_records WHERE kind='daily' AND date=? ORDER BY sequence DESC LIMIT 1", (date,)).fetchone()
            return self._load(connection, row[0]) if row else None

    def list_open(self, kind: TaskKind | None = None) -> list[ExecutionRecord]:
        if not self.db_path.exists():
            return []
        with self._connection() as connection:
            rows = connection.execute("SELECT run_id FROM execution_records WHERE state='pending' AND (? IS NULL OR kind=?) ORDER BY sequence", (kind, kind)).fetchall()
            return [self._load(connection, row[0]) for row in rows]

    def create(self, snapshot: FrozenSnapshot) -> ExecutionRecord:
        validate_snapshot(snapshot)
        if snapshot.instance_id != self.instance_id:
            raise RecoveryInvalidState("snapshot belongs to another instance")
        with self._connection(write=True) as connection:
            old = self._load(connection, snapshot.run_id)
            if old is not None:
                if old.snapshot != snapshot:
                    raise RecoveryConflict("run snapshot is already frozen")
                return old
            if snapshot.kind == "daily" and connection.execute("SELECT 1 FROM execution_records WHERE kind='daily' AND date=? AND state='pending'", (snapshot.date,)).fetchone():
                raise RecoveryConflict("same-day Daily task is unfinished")
            record = initial_record(snapshot)
            connection.execute("INSERT INTO execution_records(run_id,instance_id,snapshot_json,kind,date,state,revision,steps_json) VALUES(?,?,?,?,?,?,?,?)",
                               (snapshot.run_id, self.instance_id, canonical_json(asdict(snapshot)), snapshot.kind, snapshot.date,
                                record.state, record.revision, canonical_json(record.steps)))
            return record

    def append_event(self, run_id: str, event: RecoveryEvent, *, expected_revision: int) -> ExecutionRecord:
        if not self.db_path.exists():
            raise RecoveryInvalidState("unknown recovery task")
        with self._connection(write=True) as connection:
            old = self._load(connection, run_id)
            if old is None:
                raise RecoveryInvalidState("unknown recovery task")
            body = canonical_json(asdict(event))
            previous = connection.execute("SELECT event_json FROM recovery_events WHERE run_id=? AND event_id=?", (run_id, event.event_id)).fetchone()
            if previous:
                if previous[0] != body:
                    raise RecoveryConflict("event identity already has another payload")
                return old
            if old.revision != expected_revision:
                raise RecoveryConflict("recovery revision changed")
            result = transition(old, event)
            connection.execute("INSERT INTO recovery_events VALUES(?,?,?,?)", (run_id, event.event_id, result.revision, body))
            connection.execute("UPDATE execution_records SET state=?, revision=?, steps_json=? WHERE run_id=? AND revision=?",
                               (result.state, result.revision, canonical_json(result.steps), run_id, expected_revision))
            return result

    @contextmanager
    def lock(self, scope):
        if scope not in {"daily", "monitor", "projection"} or self.dry_run:
            raise RecoveryInvalidState("invalid or dry-run execution lock")
        ident = threading.get_ident()
        with self._mutex:
            held = self._locks.get(scope)
            if held:
                if held[0] != ident:
                    raise RecoveryBusy("execution already locked")
                held[1] += 1
            else:
                self.directory.mkdir(parents=True, exist_ok=True)
                handle = (self.directory / (".quantagent-recovery-" + scope + ".lock")).open("a+b")
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    handle.close()
                    raise RecoveryBusy("execution already locked") from exc
                self._locks[scope] = [ident, 1, handle]
        try:
            yield
        finally:
            with self._mutex:
                held = self._locks[scope]
                held[1] -= 1
                if held[1] == 0:
                    handle = held[2]
                    handle.seek(0)
                    try:
                        if os.name == "nt":
                            import msvcrt
                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    finally:
                        handle.close()
                        del self._locks[scope]
