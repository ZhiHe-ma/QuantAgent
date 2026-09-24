"""Private SQLite reservation and append-only audit for one P5 Agent handoff."""

from __future__ import annotations

import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .contracts import ContractError, canonical_json, parse_aware_timestamp, utc_now
from .p5_registry import RAW_NAMES


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HASH = re.compile(r"^[a-f0-9]{64}$")
_NONTERMINAL = (
    "admitted", "parent_running", "parent_completed", "handoff_ready",
    "child_running",
)
_TERMINAL = frozenset({"completed", "failed", "cancelled", "timed_out", "interrupted"})
_NEXT = {
    "admitted": "parent_running",
    "parent_running": "parent_completed",
    "parent_completed": "handoff_ready",
    "handoff_ready": "child_running",
    "child_running": "completed",
}
_HASH_FIELDS = frozenset({
    "source_packet_sha256", "source_report_sha256", "bundle_sha256",
    "handoff_sha256", "catalog_sha256", "policy_sha256",
})
_FIELDS = frozenset({
    "parent_id", "child_id", "source_packet_sha256", "source_report_sha256",
    "raw_hashes_json", "bundle_sha256", "handoff_sha256", "catalog_sha256",
    "policy_sha256", "permissions_json", "started_at", "ended_at",
    "wall_ms", "handoff_calls", "model_cost_minor", "failure_code",
})
_FAILURE_CODES = frozenset({
    "admission_rejected", "source_invalid", "parent_failed", "handoff_invalid",
    "child_failed", "deadline_exceeded", "cancel_requested", "process_interrupted",
    "internal_error",
})


class LedgerError(RuntimeError):
    """P5 chain state is invalid or cannot be persisted."""


class IdempotencyConflict(LedgerError):
    """A request ID was already reserved for different evidence."""


def _safe_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise LedgerError(f"{label} must be a safe bounded identifier")
    return value


def _safe_hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise LedgerError(f"{label} must be a lowercase SHA-256")
    return value


def _validated_fields(fields: dict[str, Any]) -> dict[str, Any]:
    if not set(fields) <= _FIELDS:
        raise LedgerError("chain transition contains an unknown audit field")
    output: dict[str, Any] = {}
    for key, value in fields.items():
        if key in ("parent_id", "child_id"):
            output[key] = _safe_id(value, key)
        elif key in _HASH_FIELDS:
            output[key] = _safe_hash(value, key)
        elif key == "raw_hashes_json":
            if not isinstance(value, dict) or set(value) != set(RAW_NAMES):
                raise LedgerError("raw hashes must pin all four SEC responses")
            output[key] = canonical_json({name: _safe_hash(value[name], name)
                                          for name in RAW_NAMES})
        elif key == "permissions_json":
            if (not isinstance(value, list) or value != sorted(set(value))
                    or not set(value) <= {"filesystem:read", "filesystem:write"}):
                raise LedgerError("audit permissions are invalid")
            output[key] = canonical_json(value)
        elif key in ("started_at", "ended_at"):
            try:
                parse_aware_timestamp(value, key)
            except ContractError as exc:
                raise LedgerError("audit timestamp is invalid") from exc
            output[key] = value
        elif key == "wall_ms":
            if type(value) is not int or not 0 <= value <= 120_000:
                raise LedgerError("audit wall time exceeds route budget")
            output[key] = value
        elif key == "handoff_calls":
            if type(value) is not int or value not in (0, 1):
                raise LedgerError("audit handoff count exceeds route budget")
            output[key] = value
        elif key == "model_cost_minor":
            if type(value) is not int or value != 0:
                raise LedgerError("audit model cost differs from zero budget")
            output[key] = value
        elif key == "failure_code":
            if value not in _FAILURE_CODES:
                raise LedgerError("audit failure code is not allowed")
            output[key] = value
    return output


class HandoffLedger:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir():
            raise LedgerError("P5 private run root is not a directory")
        self.path = self.root / "p5_handoff.sqlite3"
        if self.path.is_symlink():
            raise LedgerError("P5 audit database path is a symlink")
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1):
                    raise LedgerError("unsupported P5 audit schema version")
                connection.executescript("""
                    CREATE TABLE IF NOT EXISTS chains (
                        chain_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        parent_id TEXT,
                        child_id TEXT,
                        source_packet_sha256 TEXT,
                        source_report_sha256 TEXT,
                        raw_hashes_json TEXT,
                        bundle_sha256 TEXT,
                        handoff_sha256 TEXT,
                        catalog_sha256 TEXT,
                        policy_sha256 TEXT,
                        permissions_json TEXT,
                        started_at TEXT NOT NULL,
                        ended_at TEXT,
                        wall_ms INTEGER,
                        handoff_calls INTEGER NOT NULL DEFAULT 0,
                        model_cost_minor INTEGER NOT NULL DEFAULT 0,
                        failure_code TEXT
                    );
                    CREATE TABLE IF NOT EXISTS requests (
                        request_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL,
                        chain_id TEXT NOT NULL UNIQUE REFERENCES chains(chain_id)
                    );
                    CREATE TABLE IF NOT EXISTS events (
                        chain_id TEXT NOT NULL REFERENCES chains(chain_id),
                        seq INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        PRIMARY KEY(chain_id, seq)
                    );
                """)
                connection.execute("PRAGMA user_version = 1")
        except sqlite3.Error as exc:
            raise LedgerError("cannot initialize P5 audit database") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def reserve(self, request_id: str, fingerprint: str) -> tuple[str, bool]:
        _safe_id(request_id, "request_id")
        _safe_hash(fingerprint, "fingerprint")
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT fingerprint, chain_id FROM requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if existing["fingerprint"] != fingerprint:
                        raise IdempotencyConflict(
                            "request ID was used for different evidence")
                    return existing["chain_id"], False
                chain_id = f"p5-{uuid.uuid4().hex}"
                at = utc_now()
                connection.execute(
                    "INSERT INTO chains(chain_id,status,started_at) VALUES(?,?,?)",
                    (chain_id, "admitted", at),
                )
                connection.execute(
                    "INSERT INTO requests(request_id,fingerprint,chain_id) VALUES(?,?,?)",
                    (request_id, fingerprint, chain_id),
                )
                connection.execute(
                    "INSERT INTO events(chain_id,seq,status,at,payload_json) "
                    "VALUES(?,?,?,?,?)",
                    (chain_id, 1, "admitted", at, "{}"),
                )
                return chain_id, True
        except sqlite3.Error as exc:
            raise LedgerError("cannot reserve P5 request") from exc

    def transition(self, chain_id: str, status: str, **fields: Any) -> dict[str, Any]:
        _safe_id(chain_id, "chain_id")
        if status not in (*_NONTERMINAL, *_TERMINAL):
            raise LedgerError("unknown P5 chain status")
        values = _validated_fields(fields)
        if status in _TERMINAL and status != "completed":
            if "failure_code" not in values:
                raise LedgerError("terminal failure requires an enumerated failure code")
            values.setdefault("ended_at", utc_now())
        elif "failure_code" in values:
            raise LedgerError("failure code requires terminal failure status")
        if status == "completed":
            values.setdefault("ended_at", utc_now())
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT status FROM chains WHERE chain_id = ?", (chain_id,),
                ).fetchone()
                if current is None:
                    raise LedgerError("unknown P5 chain")
                previous = current["status"]
                if previous in _TERMINAL or (
                    status not in _TERMINAL and _NEXT.get(previous) != status
                ) or (status == "completed" and previous != "child_running"):
                    raise LedgerError(f"illegal P5 chain transition {previous} -> {status}")
                if values:
                    assignments = ", ".join(f"{key} = ?" for key in values)
                    connection.execute(
                        f"UPDATE chains SET status = ?, {assignments} WHERE chain_id = ?",
                        (status, *values.values(), chain_id),
                    )
                else:
                    connection.execute(
                        "UPDATE chains SET status = ? WHERE chain_id = ?",
                        (status, chain_id),
                    )
                seq = connection.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE chain_id = ?",
                    (chain_id,),
                ).fetchone()[0]
                at = utc_now()
                payload = dict(fields)
                connection.execute(
                    "INSERT INTO events(chain_id,seq,status,at,payload_json) "
                    "VALUES(?,?,?,?,?)",
                    (chain_id, seq, status, at, canonical_json(payload)),
                )
        except sqlite3.Error as exc:
            raise LedgerError("cannot transition P5 chain") from exc
        return self.get(chain_id)

    def get(self, chain_id: str) -> dict[str, Any]:
        _safe_id(chain_id, "chain_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT c.*, r.request_id, r.fingerprint FROM chains c JOIN requests r "
                    "ON r.chain_id = c.chain_id WHERE c.chain_id = ?", (chain_id,),
                ).fetchone()
                if row is None:
                    raise LedgerError("unknown P5 chain")
                record = dict(row)
                for key in ("raw_hashes_json", "permissions_json"):
                    if record[key] is not None:
                        import json
                        record[key] = json.loads(record[key])
                record["events"] = [dict(event) for event in connection.execute(
                    "SELECT seq,status,at,payload_json FROM events WHERE chain_id = ? "
                    "ORDER BY seq", (chain_id,),
                )]
                for event in record["events"]:
                    import json
                    event["payload"] = json.loads(event.pop("payload_json"))
                return record
        except sqlite3.Error as exc:
            raise LedgerError("cannot read P5 chain") from exc

    def get_by_request(self, request_id: str) -> dict[str, Any] | None:
        _safe_id(request_id, "request_id")
        try:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT chain_id FROM requests WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise LedgerError("cannot read P5 request") from exc
        return None if row is None else self.get(row["chain_id"])

    def recover_interrupted(self) -> int:
        try:
            with self._connection() as connection:
                rows = connection.execute(
                    "SELECT chain_id FROM chains WHERE status IN "
                    "('admitted','parent_running','parent_completed',"
                    "'handoff_ready','child_running')"
                ).fetchall()
            for row in rows:
                self.transition(row["chain_id"], "interrupted",
                                failure_code="process_interrupted")
            return len(rows)
        except sqlite3.Error as exc:
            raise LedgerError("cannot recover interrupted P5 chains") from exc
