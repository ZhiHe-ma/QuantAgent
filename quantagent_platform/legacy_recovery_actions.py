"""Read-only status and explicit human actions over recovery ports."""
from datetime import datetime
import uuid

from .legacy_daily_recovery import resume_daily
from .legacy_monitor_recovery import resume_news
from .legacy_ports import DailyPorts, MonitorPorts
from .recovery.contracts import (JsonObject, RecoveryAction, RecoveryEvent, RecoveryInvalidState, RecoveryStore)
from .recovery.rules import task_resolved


def describe_record(record):
    return {"run_id": record.snapshot.run_id, "kind": record.snapshot.kind, "date": record.snapshot.date,
            "state": record.state, "revision": record.revision, "steps": dict(record.steps)}


def run_recovery_action(store: RecoveryStore, *, action: RecoveryAction, run_id: str | None = None,
                        reason: str | None = None, dry_run: bool = False,
                        daily: DailyPorts | None = None, monitor: MonitorPorts | None = None) -> JsonObject:
    if action not in {"status", "retry", "confirm-sent", "confirm-not-sent", "abandon"}:
        raise RecoveryInvalidState("unknown recovery action")
    if action != "status" and not run_id:
        raise RecoveryInvalidState("action requires run_id")
    if action == "abandon" and not (reason or "").strip():
        raise RecoveryInvalidState("abandon requires a reason")
    if action == "status":
        records = [store.get(run_id)] if run_id else store.list_open()
        if run_id and records[0] is None:
            raise RecoveryInvalidState("task does not exist")
        return {"status": "read_only", "tasks": [describe_record(r) for r in records]}
    record = store.get(run_id)
    if record is None:
        raise RecoveryInvalidState("task does not exist")
    if dry_run:
        return {"status": "dry_run", "action": action, "task": describe_record(record)}
    with store.lock(record.snapshot.kind):
        record = store.get(run_id)
        if record.state == "abandoned":
            raise RecoveryInvalidState("abandoned tasks cannot be changed")
        def append(step, status, detail=None):
            return store.append_event(run_id, RecoveryEvent(uuid.uuid4().hex, step, status,
                datetime.now().astimezone().isoformat(), detail or {}), expected_revision=record.revision)
        if action == "retry":
            if record.snapshot.kind == "daily" and daily is not None and daily.recovery is store:
                return resume_daily(daily, record, explicit_retry=True)
            if record.snapshot.kind == "monitor" and monitor is not None and monitor.recovery is store:
                return resume_news(monitor, record)
            raise RecoveryInvalidState("retry requires matching owned recovery ports")
        if action == "abandon":
            if record.state == "completed":
                raise RecoveryInvalidState("completed tasks cannot be abandoned")
            record = append("task", "abandoned", {"reason": reason.strip(), "source": "manual"})
        else:
            if record.snapshot.kind != "daily":
                raise RecoveryInvalidState("message confirmation is only valid for Daily")
            target = "confirmed" if action == "confirm-sent" else "failed"
            if record.steps.get("message") == target:
                return {"status": "unchanged", "task": describe_record(record)}
            if record.steps.get("message") == "running":
                record = append("message", "unknown", {"source": "provider", "error_code": "interrupted_send"})
            if record.steps.get("message") != "unknown":
                raise RecoveryInvalidState("only unknown delivery accepts manual confirmation")
            record = append("message", target, {"source": "manual", "action": action})
            if task_resolved(record):
                record = append("task", "completed")
        return {"status": "updated", "task": describe_record(record)}
