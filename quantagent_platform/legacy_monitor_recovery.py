"""Observe before inference; acknowledge only owned durable projections."""
import hashlib
import json

from .legacy_daily_recovery import append_step
from .legacy_ports import MonitorPorts
from .recovery.contracts import ExecutionRecord, JsonObject, RecoveryBusy, RecoveryInvalidState, StepResult
from .recovery.rules import decode_json, freeze_snapshot, task_resolved

MONITOR_SYSTEM_PROMPT = (
        "你是一个极端保守的微观量化因子标记器。请直接分析给定新闻对加密货币（主要是BTC与主流代币）价格的影响。\n"
        "评级纪律必须极硬：Low=普通观点/行情复盘/轻微产品动态；Medium=有方向但冲击路径间接；High=有清晰、直接、可交易的价格冲击路径；Critical=只允许非线性事件，例如交易所宕机、提现暂停、重大监管裁决、ETF突发批准或否决、巨额黑客攻击、大型钱包向交易所转移、宏观数据严重超预期。\n"
        "禁止把普通分析稿、行情直播、技术面评论、may/could/analyst 类文章评为 Critical。正常情况下 Critical 应极少出现。\n"
        "必须输出标准 JSON，严禁 Markdown、解释性文字、多余字段。格式如下：\n"
        '{"sentiment": "利多" | "利空" | "中性", "weight": "Critical" | "High" | "Medium" | "Low", "reason": "50字以内的极端精炼异动逻辑"}'
    )


class NewsInferenceError(ValueError):
    def __init__(self, raw_result):
        super().__init__("news result could not be parsed or calibrated")
        self.raw_result = raw_result


def infer_news(ports, body):
    news = body["news"]
    title = ports.clamp_str(news.get("title", ""), 180)
    text = ports.clamp_str(news.get("body", ""), 800)
    prompt = f"来源: {ports.clamp_str(news.get('source', 'rss'), 40)}\n新闻标题: {title}\n新闻正文: {text}\n链接: {ports.clamp_str(news.get('url', ''), 240)}"
    raw = ports.request_deepseek(prompt, use_r1=False, system_prompt=MONITOR_SYSTEM_PROMPT)
    try:
        return parse_news_result(ports, body, raw)
    except Exception as exc:
        raise NewsInferenceError(raw) from exc


def parse_news_result(ports, body, raw):
    news = body["news"]
    title = ports.clamp_str(news.get("title", ""), 180)
    text = ports.clamp_str(news.get("body", ""), 800)
    decision = json.loads(ports.strip_json_fence(raw))
    if (not isinstance(decision, dict) or decision.get("sentiment") not in {"利多", "利空", "中性"}
            or decision.get("weight") not in {"Critical", "High", "Medium", "Low"}
            or not str(decision.get("reason", "")).strip()):
        raise ValueError("invalid news decision")
    factor = {"id": body["news_id"], "fingerprint": body["fingerprint"], "time": ports.now().strftime("%H:%M:%S"),
              "source": ports.clamp_str(news.get("source", "rss"), 40), "published": ports.clamp_str(news.get("published", ""), 40),
              "title": title, "url": ports.clamp_str(news.get("url", ""), 240),
              "sentiment": ports.clamp_str(decision["sentiment"], 12), "weight": ports.clamp_str(decision["weight"], 12),
              "reason": ports.clamp_str(decision["reason"], 80)}
    calibrated, reason = ports.calibrate_factor_weight(title=title, body=text, weight=factor["weight"], reason=factor["reason"])
    if calibrated != factor["weight"]:
        factor.update(calibrated_from=factor["weight"], calibration_reason=reason, weight=calibrated)
    return raw, factor


def _capture_state(ports, date):
    while True:
        try:
            return ports.capture_state(date)
        except RecoveryBusy:
            ports.sleep(1)


def resume_news(ports: MonitorPorts, record: ExecutionRecord) -> JsonObject:
    if ports.dry_run or ports.recovery is None or not callable(ports.capture_state) or not callable(ports.project_news):
        raise RecoveryInvalidState("incomplete or dry Monitor recovery ports")
    with ports.recovery.lock("monitor"):
        record = ports.recovery.get(record.snapshot.run_id)
        if record is None or record.snapshot.kind != "monitor" or record.state == "abandoned":
            raise RecoveryInvalidState("task cannot execute as Monitor")
        if record.state == "completed":
            return {"status": "skipped", "run_id": record.snapshot.run_id, "model_calls": 0}
        body = decode_json(record.snapshot.payload_json)
        _capture_state(ports, body["target_date"])
        frozen = next((e.detail for e in record.events if e.step == "model" and e.status == "succeeded"), None)
        calls = 0
        if frozen is None:
            previous = next((e.detail for e in reversed(record.events) if e.step == "model" and "attempts" in e.detail), {})
            attempts = previous.get("attempts", 0)
            record = append_step(ports, record, "model", "running", {"attempts": attempts})
            calls = 1
            # Only model/parse/calibration errors consume the model retry budget.
            try:
                raw, factor = infer_news(ports, body)
                decision = "pooled" if ports.weight_rank(factor["weight"]) >= ports.weight_rank(ports.min_store_weight) else "low_weight_discarded"
                detail = {"attempts": attempts, "raw_result": raw, "factor": factor, "decision": decision}
            except Exception as exc:
                attempts += 1
                detail = {"attempts": attempts, "raw_result": getattr(exc, "raw_result", ""), "factor": None,
                          "decision": "quarantined" if attempts >= ports.max_news_ai_retries else None}
            record = append_step(ports, record, "model", "succeeded" if detail["decision"] is not None else "failed", detail)
            frozen = detail
        projections = ["quarantine"]
        if record.steps["model"] == "succeeded":
            if frozen["decision"] == "pooled": projections.append("buffer")
            projections.extend(["dedup", "fingerprint"])
        for projection in projections:
            if record.steps.get(projection) == "succeeded":
                continue
            record = append_step(ports, record, projection, "running")
            try:
                result = ports.project_news(record, projection)
            except Exception:
                result = StepResult("failed", {"error_code": "news_projection"})
            record = append_step(ports, record, projection, result.status, result.detail)
            if result.status != "succeeded":
                break
        if task_resolved(record):
            record = append_step(ports, record, "task", "completed")
        return {"status": record.state, "run_id": record.snapshot.run_id, "model_calls": calls, "steps": dict(record.steps)}


def run_monitor_recovery(ports: MonitorPorts) -> None:
    if ports.dry_run or ports.recovery is None or not callable(ports.capture_state) or not callable(ports.project_news):
        raise RecoveryInvalidState("incomplete or dry Monitor recovery ports")
    with ports.recovery.lock("monitor"):
        _capture_state(ports, ports.now().strftime("%Y-%m-%d"))
        while True:
            used, seen = 0, set()
            date = ports.now().strftime("%Y-%m-%d")
            state = _capture_state(ports, date)
            for record in ports.recovery.list_open("monitor"):
                body = decode_json(record.snapshot.payload_json)
                seen.add(body["fingerprint"])
                if record.steps["model"] != "succeeded" and used >= ports.max_news_per_cycle:
                    continue
                used += resume_news(ports, record)["model_calls"]
            state = _capture_state(ports, date)
            for news in ports.fetch_crypto_flash_news():
                if used >= ports.max_news_per_cycle:
                    break
                news_id, fingerprint = str(news.get("id", "")).strip(), ports.news_fingerprint(news)
                if not news_id or fingerprint in seen or news_id in state["dedup"] or fingerprint in state["fingerprint"]:
                    continue
                seen.add(fingerprint)
                body = {"news": news, "news_id": news_id, "fingerprint": fingerprint, "target_date": date,
                        "observed_at": ports.now().astimezone().isoformat()}
                run_id = "news_" + date.replace("-", "") + "_" + hashlib.sha256((news_id+":"+fingerprint).encode("utf-8")).hexdigest()[:32]
                record = ports.recovery.get(run_id)
                if record is not None and record.state in {"completed", "abandoned"}:
                    continue
                if record is None:
                    snapshot = freeze_snapshot(instance_id=ports.recovery.instance_id, run_id=run_id, kind="monitor",
                        date=date, created_at=body["observed_at"], payload=body)
                    record = ports.recovery.create(snapshot)
                    legacy = state["quarantine"].get(fingerprint, {})
                    if legacy.get("attempts", 0) >= ports.max_news_ai_retries:
                        record = append_step(ports, record, "model", "succeeded", {"attempts": legacy["attempts"],
                            "raw_result": legacy.get("raw_preview", ""), "factor": None, "decision": "quarantined", "source": "legacy"})
                    elif legacy.get("attempts", 0):
                        record = append_step(ports, record, "model", "pending", {"attempts": legacy["attempts"], "source": "legacy"})
                used += resume_news(ports, record)["model_calls"]
                state = _capture_state(ports, date)
            ports.sleep(180)
