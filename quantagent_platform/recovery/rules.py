"""Deterministic validation and reduction of frozen research and events."""
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Any, Callable

from .contracts import (SCHEMA_VERSION, ExecutionRecord, FrozenSnapshot, JsonObject,
                        RecoveryConflict, RecoveryEvent, RecoveryInvalidState, TaskKind)


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RecoveryInvalidState("recovery value is not finite JSON") from exc


def decode_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RecoveryInvalidState("duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise RecoveryInvalidState("non-finite JSON value")
    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (TypeError, ValueError) as exc:
        raise RecoveryInvalidState("invalid recovery JSON") from exc


def validate_time(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise RecoveryInvalidState("recovery timestamps must include timezone") from exc


def freeze_snapshot(*, instance_id: str, run_id: str, kind: TaskKind, date: str,
                    created_at: str, payload: JsonObject) -> FrozenSnapshot:
    body = canonical_json(payload)
    result = FrozenSnapshot(SCHEMA_VERSION, instance_id, run_id, kind, date, created_at,
                            body, hashlib.sha256(body.encode("utf-8")).hexdigest())
    validate_snapshot(result)
    return result


def validate_snapshot(snapshot: FrozenSnapshot) -> None:
    if type(snapshot.version) is not int or snapshot.version != SCHEMA_VERSION:
        raise RecoveryInvalidState("unsupported recovery version")
    if not snapshot.instance_id or not snapshot.run_id or snapshot.kind not in {"daily", "monitor"}:
        raise RecoveryInvalidState("invalid recovery identity")
    try:
        if date.fromisoformat(snapshot.date).isoformat() != snapshot.date:
            raise ValueError()
    except (TypeError, ValueError) as exc:
        raise RecoveryInvalidState("invalid recovery date") from exc
    validate_time(snapshot.created_at)
    body = decode_json(snapshot.payload_json)
    if not isinstance(body, dict) or canonical_json(body) != snapshot.payload_json:
        raise RecoveryInvalidState("snapshot is not a canonical JSON object")
    if hashlib.sha256(snapshot.payload_json.encode("utf-8")).hexdigest() != snapshot.sha256:
        raise RecoveryInvalidState("snapshot hash mismatch")
    if snapshot.kind == "daily":
        required = {"signal_id", "started_at", "report", "message", "capsule", "metrics",
                    "compact_news", "analysis", "previous_memory", "memory_target",
                    "report_preimage", "memory_preimage", "audit_facts", "audit_preimage", "channel_id"}
        if not required <= body.keys():
            raise RecoveryInvalidState("incomplete Daily snapshot")
        if not all(isinstance(body[x], dict) for x in ("capsule", "metrics", "previous_memory", "memory_target", "audit_facts")):
            raise RecoveryInvalidState("invalid Daily objects")
        if not all(isinstance(body[x], str) and body[x].strip() for x in ("report", "message", "analysis", "signal_id")):
            raise RecoveryInvalidState("invalid Daily text")
        if body["capsule"].get("date") != snapshot.date or not isinstance(body["compact_news"], list):
            raise RecoveryInvalidState("Daily date or factors mismatch")
        facts = body["audit_facts"]
        if (not isinstance(facts.get("run"), dict) or not isinstance(facts.get("signal"), dict)
                or facts["run"].get("run_id") != snapshot.run_id
                or facts["signal"].get("signal_id") != body["signal_id"]):
            raise RecoveryInvalidState("audit identity mismatch")
        if any(facts["run"].get(x) for x in ("report_written", "wecom_sent", "memory_saved")):
            raise RecoveryInvalidState("research snapshot cannot claim delivery")
        validate_time(body["started_at"])
    else:
        required = {"news", "news_id", "fingerprint", "target_date", "observed_at"}
        if (not required <= body.keys() or not isinstance(body["news"], dict)
                or not body["news_id"] or not body["fingerprint"] or body["target_date"] != snapshot.date):
            raise RecoveryInvalidState("incomplete Monitor observation")
        validate_time(body["observed_at"])


def initial_record(snapshot: FrozenSnapshot) -> ExecutionRecord:
    steps = dict.fromkeys(("report", "message", "memory", "audit") if snapshot.kind == "daily" else ("model",), "pending")
    return ExecutionRecord(snapshot, 0, "pending", steps, ())


def task_resolved(record: ExecutionRecord) -> bool:
    steps = record.steps
    if record.snapshot.kind == "daily":
        return (steps.get("report") == "succeeded" and steps.get("audit") == "succeeded"
                and steps.get("memory") in {"succeeded", "superseded"}
                and steps.get("message") in {"confirmed", "not_configured"})
    return (steps.get("model") == "succeeded"
            and all(steps.get(x) == "succeeded" for x in ("dedup", "fingerprint", "quarantine"))
            and ("buffer" not in steps or steps["buffer"] == "succeeded"))


def transition(record: ExecutionRecord, event: RecoveryEvent) -> ExecutionRecord:
    validate_time(event.occurred_at)
    if not event.event_id or not isinstance(event.detail, dict):
        raise RecoveryInvalidState("invalid event identity or detail")
    detail = decode_json(canonical_json(event.detail))  # detach caller-owned mutable input
    event = replace(event, detail=detail)
    if record.state == "abandoned":
        raise RecoveryInvalidState("abandoned tasks cannot be changed")
    steps, state = dict(record.steps), record.state
    current = steps.get(event.step, "pending")
    if event.step == "task":
        if event.status == "completed":
            if not task_resolved(record):
                raise RecoveryInvalidState("unresolved steps cannot complete")
            state = "completed"
        elif event.status == "abandoned" and str(detail.get("reason", "")).strip():
            state = "abandoned"
        elif event.status == "retry_requested":
            if state == "completed" and steps.get("message") != "not_configured":
                raise RecoveryInvalidState("completed task has no retryable notification")
            state = "pending"
            if steps.get("message") == "not_configured":
                steps["message"] = "pending"
        else:
            raise RecoveryInvalidState("invalid task action")
    elif event.step == "audit_payload":
        if event.status != "frozen" or not isinstance(detail.get("payload"), dict):
            raise RecoveryInvalidState("invalid audit freeze")
        previous = next((e.detail["payload"] for e in record.events if e.step == "audit_payload"), None)
        if previous is not None and previous != detail["payload"]:
            raise RecoveryConflict("audit payload is already frozen")
    elif event.step == "message":
        if event.status not in {"pending", "running", "confirmed", "failed", "unknown", "not_configured", "needs_review"}:
            raise RecoveryInvalidState("invalid delivery state")
        if current == "unknown" and (event.status == "running" or (event.status == "failed" and detail.get("source") != "manual")):
            raise RecoveryInvalidState("unknown delivery needs manual confirmation")
        if current == "confirmed" and event.status != "confirmed":
            raise RecoveryInvalidState("confirmed delivery cannot be undone")
        if current == "not_configured" and event.status == "running":
            raise RecoveryInvalidState("unconfigured notification requires explicit retry")
        steps[event.step] = event.status
    elif event.step in {"report", "memory", "audit", "model", "buffer", "dedup", "fingerprint", "quarantine"}:
        if event.status not in {"pending", "running", "succeeded", "failed", "needs_review", "superseded"}:
            raise RecoveryInvalidState("invalid local step state")
        if event.status == "superseded" and event.step != "memory":
            raise RecoveryInvalidState("only Memory can be superseded")
        if current in {"succeeded", "superseded"} and event.status == "running":
            raise RecoveryInvalidState("resolved local step cannot execute again")
        if event.step == "model" and event.status == "succeeded":
            if detail.get("decision") not in {"pooled", "low_weight_discarded", "quarantined"}:
                raise RecoveryInvalidState("missing frozen news decision")
            old = next((e.detail for e in record.events if e.step == "model" and e.status == "succeeded"), None)
            if old is not None and old != detail:
                raise RecoveryConflict("news result is already frozen")
            for step in ("dedup", "fingerprint", "quarantine"):
                steps.setdefault(step, "pending")
            if detail["decision"] == "pooled":
                steps.setdefault("buffer", "pending")
        steps[event.step] = event.status
    else:
        raise RecoveryInvalidState("unknown recovery step")
    return ExecutionRecord(record.snapshot, record.revision + 1, state, steps, record.events + (event,))


def build_memory_target(state: JsonObject, capsule: JsonObject, clamp: Callable[..., str]) -> JsonObject:
    previous = state.get("last_daily_capsule", {}) or {}
    rolling = list(state.get("rolling_7d", []) or [])
    normalized = {"date": clamp(capsule["date"], 20), "risk_regime": clamp(capsule.get("risk_regime", "unknown"), 32),
                  "btc_bias": clamp(capsule.get("btc_bias", "unknown"), 32), "confidence": capsule.get("confidence", 0),
                  "core_thesis": clamp(capsule.get("core_thesis", ""), 220), "invalid_if": clamp(capsule.get("invalid_if", ""), 160),
                  "watch_items": [clamp(x, 50) for x in list(capsule.get("watch_items", []))[:5]],
                  "today_check": clamp(capsule.get("today_check", ""), 180)}
    if previous and previous.get("date") and previous["date"] != normalized["date"]:
        rolling.append({"date": clamp(previous["date"], 20), "bias": previous.get("btc_bias", "unknown"),
                        "core": clamp(previous.get("core_thesis", ""), 180)})
    seen, reverse = set(), []
    for item in reversed(rolling):
        if not isinstance(item, dict):
            continue
        item_date = clamp(item.get("date", ""), 20)
        if not item_date or item_date == normalized["date"] or item_date in seen:
            continue
        seen.add(item_date)
        reverse.append({"date": item_date, "bias": clamp(item.get("bias", "unknown"), 32), "core": clamp(item.get("core", ""), 180)})
    return {"last_daily_capsule": normalized, "rolling_7d": list(reversed(reverse))[-7:]}


def freeze_audit_payload(snapshot: FrozenSnapshot, steps: dict[str, str], at: str) -> JsonObject:
    validate_snapshot(snapshot)
    validate_time(at)
    if steps.get("report") != "succeeded" or steps.get("memory") not in {"succeeded", "superseded"}:
        raise RecoveryInvalidState("audit requires resolved report and Memory")
    body = decode_json(snapshot.payload_json)
    payload = body["audit_facts"]
    payload["run"].update(report_written=True, wecom_sent=steps.get("message") == "confirmed",
                          memory_saved=steps.get("memory") == "succeeded", completed_at=at)
    payload["expected_canonical_signal_id"] = body["audit_preimage"]
    return payload
