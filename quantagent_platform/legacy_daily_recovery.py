"""Daily orchestration through public owned operations, without concrete IO."""
from dataclasses import asdict
import json
import uuid

from .daily_workflow import DAILY_SYSTEM_PROMPT, build_daily_prompt, render_daily_report
from .legacy_ports import DailyPorts
from .recovery.contracts import (DeliveryResult, ExecutionRecord, JsonObject, RecoveryEvent,
                                 RecoveryInvalidState, StepResult)
from .recovery.rules import build_memory_target, decode_json, freeze_audit_payload, freeze_snapshot, task_resolved


def append_step(ports, record, step, status, detail=None):
    return ports.recovery.append_event(record.snapshot.run_id,
        RecoveryEvent(uuid.uuid4().hex, step, status, ports.now().astimezone().isoformat(), detail or {}),
        expected_revision=record.revision)


def require_daily_ports(ports):
    if ports.recovery is None or any(not callable(getattr(ports, name)) for name in
        ("capture_inputs", "prepare_audit", "project_report", "project_memory", "commit_audit", "send_message", "channel_id")):
        raise RecoveryInvalidState("incomplete Daily recovery ports")


def run_daily_recovery(ports: DailyPorts) -> JsonObject:
    require_daily_ports(ports)
    if ports.dry_run:
        raise RecoveryInvalidState("dry Daily research uses the read-only legacy preview")
    today = ports.now().strftime("%Y-%m-%d")
    with ports.recovery.lock("daily"):
        record = ports.recovery.find_daily(today)
        if record is not None and record.state == "pending":
            return resume_daily(ports, record)
        if record is not None and record.state == "completed" and not ports.force_daily_run:
            return {"status": "skipped", "date": today}
        try:
            inputs = ports.capture_inputs(today)
        except RecoveryInvalidState as exc:
            return {"status": "needs_review", "date": today, "reason": str(exc)}
        memory = inputs["memory_state"]
        if record is None:
            has_report = inputs["report_preimage"] is not None
            has_memory = memory.get("last_daily_capsule", {}).get("date") == today
            if has_report and has_memory and not ports.force_daily_run:
                print("⚠️ [Daily] 历史日报与 Memory 已完成，但没有恢复凭据；沿用幂等跳过。")
                return {"status": "skipped", "date": today}
            if has_report != has_memory:
                return {"status": "needs_review", "date": today, "reason": "legacy_partial_without_snapshot"}
        started_at = ports.now().astimezone().isoformat(timespec="seconds")
        metrics = ports.fetch_market_signals()
        news = ports.read_json(ports.get_buffer_path(), [])
        if not isinstance(news, list) or any(not isinstance(x, dict) for x in news):
            raise RecoveryInvalidState("invalid Daily news buffer")
        selected = [x for x in news if x.get("weight") in {"Critical", "High"}]
        selected = selected or [x for x in news if x.get("weight") == "Medium"]
        compact = ports.compact_news_factors(selected)
        bounded = ports.clamp_memory_state(memory)
        previous = bounded.get("last_daily_capsule", {})
        prompt = build_daily_prompt(previous, bounded.get("rolling_7d", []), metrics, compact)
        analysis = ports.request_deepseek(prompt=json.dumps(prompt, ensure_ascii=False), use_r1=True, system_prompt=DAILY_SYSTEM_PROMPT)
        capsule = ports.generate_memory_capsule(today, analysis, metrics, compact)
        facts = ports.prepare_audit({"date": today, "started_at": started_at, "capsule": capsule,
            "metrics": metrics, "compact_news": compact, "previous_memory": previous, "analysis": analysis})
        report = render_daily_report(report_date=today, metrics=metrics, previous_memory=previous,
            news_factors=compact, raw_factor_count=len(selected), analysis_text=analysis)
        snapshot = freeze_snapshot(instance_id=ports.recovery.instance_id, run_id=facts["run"]["run_id"], kind="daily",
            date=today, created_at=started_at, payload={"signal_id": facts["signal"]["signal_id"],
            "started_at": started_at, "report": report, "message": f"### 📊 投研早餐内参 ({today})\n\n{analysis}",
            "capsule": capsule, "metrics": metrics, "compact_news": compact, "analysis": analysis,
            "previous_memory": previous, "memory_target": build_memory_target(memory, capsule, ports.clamp_str),
            "report_preimage": inputs["report_preimage"], "memory_preimage": inputs["memory_preimage"],
            "audit_facts": facts, "audit_preimage": inputs["audit_preimage"], "channel_id": ports.channel_id()})
        return resume_daily(ports, ports.recovery.create(snapshot))


def resume_daily(ports: DailyPorts, record: ExecutionRecord, *, explicit_retry: bool = False) -> JsonObject:
    require_daily_ports(ports)
    if ports.dry_run or record.snapshot.kind != "daily" or record.state == "abandoned":
        raise RecoveryInvalidState("task cannot execute as Daily")
    with ports.recovery.lock("daily"):
        record = ports.recovery.get(record.snapshot.run_id)
        if record is None:
            raise RecoveryInvalidState("missing Daily task")
        body = decode_json(record.snapshot.payload_json)
        if explicit_retry:
            binding = body["channel_id"] or next((e.detail.get("channel_id") for e in record.events
                if e.step == "task" and e.status == "retry_requested" and e.detail.get("channel_id")), None)
            record = append_step(ports, record, "task", "retry_requested", {"channel_id": binding or ports.channel_id()})
        audit = {"status": "skipped", "reason": "memory_not_saved"}
        def result():
            response = {"report": body["report"], "capsule": body["capsule"], "audit": audit}
            if record.state != "completed":
                response.update(status="needs_review" if "needs_review" in record.steps.values() else "pending",
                                run_id=record.snapshot.run_id, steps=dict(record.steps))
            return response
        for step, callback in (("report", ports.project_report),):
            if record.steps[step] != "succeeded":
                record = append_step(ports, record, step, "running")
                try:
                    projected = callback(record.snapshot)
                except Exception:
                    projected = StepResult("failed", {"error_code": "report_operation"})
                record = append_step(ports, record, step, projected.status, projected.detail)
                if projected.status != "succeeded":
                    return result()
        if record.steps["message"] == "running":
            record = append_step(ports, record, "message", "unknown", {"source": "provider", "error_code": "interrupted_send"})
        manual_no = max((i for i, e in enumerate(record.events) if e.step == "message"
                        and e.status == "failed" and e.detail.get("source") == "manual"), default=-1)
        requires_retry = manual_no >= 0 and not any(e.step == "task" and e.status == "retry_requested"
                                                   for e in record.events[manual_no+1:])
        if record.steps["message"] not in {"confirmed", "unknown", "not_configured"} and not requires_retry:
            bound = body["channel_id"] or next((e.detail.get("channel_id") for e in record.events
                if e.step == "task" and e.status == "retry_requested" and e.detail.get("channel_id")), None)
            channel = ports.channel_id()
            if bound is not None and channel != bound:
                record = append_step(ports, record, "message", "needs_review", {"error_code": "channel_changed"})
            elif channel is None:
                record = append_step(ports, record, "message", "not_configured", {"source": "configuration"})
            else:
                record = append_step(ports, record, "message", "running", {"channel_id": channel})
                try:
                    delivery = ports.send_message(body["message"])
                    if isinstance(delivery, bool):
                        delivery = DeliveryResult("confirmed" if delivery else "unknown", "legacy", channel, None)
                    if not isinstance(delivery, DeliveryResult) or delivery.channel_id != channel:
                        delivery = DeliveryResult("unknown", "provider", channel, "untrusted_callback")
                except Exception:
                    delivery = DeliveryResult("unknown", "provider", channel, "send_operation")
                record = append_step(ports, record, "message", delivery.status, asdict(delivery))
        if record.steps["memory"] not in {"succeeded", "superseded"}:
            record = append_step(ports, record, "memory", "running")
            try:
                projected = ports.project_memory(record.snapshot)
            except Exception:
                projected = StepResult("failed", {"error_code": "memory_operation"})
            record = append_step(ports, record, "memory", projected.status, projected.detail)
            if projected.status not in {"succeeded", "superseded"}:
                return result()
        payload = next((e.detail["payload"] for e in record.events if e.step == "audit_payload"), None)
        if payload is None:
            payload = freeze_audit_payload(record.snapshot, record.steps, ports.now().astimezone().isoformat())
            record = append_step(ports, record, "audit_payload", "frozen", {"payload": payload})
        if record.steps["audit"] != "succeeded":
            record = append_step(ports, record, "audit", "running")
            try:
                audit = ports.commit_audit(payload)
                if audit.get("status") not in {"recorded", "exists"}:
                    raise RecoveryInvalidState("unconfirmed audit result")
            except Exception:
                audit = {"status": "failed", "error_code": "audit_operation"}
            record = append_step(ports, record, "audit", "succeeded" if audit["status"] != "failed" else "failed", {"result": audit})
        else:
            audit = next(e.detail["result"] for e in reversed(record.events) if e.step == "audit" and e.status == "succeeded")
        if record.state != "completed" and task_resolved(record):
            record = append_step(ports, record, "task", "completed")
        return result()
