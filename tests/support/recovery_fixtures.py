"""Synthetic recovery inputs; never imports test cases or contacts providers."""
from typing import Any
from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch


@contextmanager
def isolated_engine(root: Path, *, dry_run: bool = False, wecom_url: str = "https://example.invalid/webhook"):
    from tests.support.paths import ROOT
    import quantagent_platform.legacy_ports as ports
    audit_factory, recovery_factory = ports.get_legacy_audit_factory(), getattr(ports, "get_legacy_recovery_factory", lambda: None)()
    requests = types.ModuleType("requests")
    requests.get = requests.post = Mock(side_effect=AssertionError("unexpected network"))
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **kw: False
    env = {"DEEPSEEK_API_KEY": "fixture", "DRY_RUN": str(dry_run).lower(), "WECOM_WEBHOOK_URL": wecom_url}
    try:
        with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {"requests": requests, "yfinance": types.ModuleType("yfinance"), "dotenv": dotenv}):
            spec = importlib.util.spec_from_file_location("recovery_engine_fixture", ROOT / "agent_engine.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.BASE_DIR = str(root)
            yield module, module.QuantAgent()
    finally:
        ports.configure_legacy_audit_factory(audit_factory)
        if recovery_factory is not None:
            ports.configure_legacy_recovery_factory(recovery_factory)


def daily_payload(date: str = "2026-10-03") -> dict[str, Any]:
    capsule = {"date": date, "risk_regime": "neutral", "btc_bias": "neutral",
               "confidence": 70, "core_thesis": "合成研究", "invalid_if": "fixture changes",
               "watch_items": ["合成观察"], "today_check": "fixture only"}
    at = date + "T08:00:00+08:00"
    run = {"run_id": "run_fixture", "trade_date": date, "started_at": at,
           "completed_at": at, "run_kind": "scheduled", "code_version": "fixture",
           "source_sha256": "a" * 64, "fast_model": "fixture", "reason_model": "fixture"}
    signal = {"signal_id": "signal_fixture", "signal_date": date, "asset": "BTC",
              "quote_asset": "USDT", "decision_horizon": "1d", "risk_regime": "neutral",
              "bias": "neutral", "confidence_raw": 70, "core_thesis": "合成研究",
              "invalid_if": "fixture changes", "today_check": "fixture only",
              "watch_items": [], "market_snapshot": {}, "previous_memory": {},
              "analysis_text": "合成研究", "data_quality_score": 90,
              "quality_flags": [], "finalized_at": at}
    return {"signal_id": "signal_fixture", "started_at": at, "report": "中文日报\n原文本\n",
            "message": "合成消息", "capsule": capsule, "metrics": {"crypto": {"BTC_Price": 60000}},
            "compact_news": [], "analysis": "合成研究", "previous_memory": {},
            "memory_target": {"last_daily_capsule": capsule.copy(), "rolling_7d": []},
            "report_preimage": None, "memory_preimage": None,
            "audit_facts": {"run": run, "signal": signal, "factors": []},
            "audit_preimage": None, "channel_id": "b" * 64}


def news_payload(date: str = "2026-10-03") -> dict[str, Any]:
    news = {"id": "news_fixture", "title": "合成新闻", "body": "fixture",
            "source": "fixture", "url": "https://example.invalid/news"}
    return {"news": news, "news_id": news["id"], "fingerprint": "c" * 64,
            "target_date": date, "observed_at": date + "T23:59:00+08:00"}


def recovery_child(root: Path, operation: str, point: str = "") -> None:
    """Child-process driver: real owned writes, fake services, no product hooks."""
    from dataclasses import replace
    from datetime import datetime, timezone, timedelta
    import json
    from quantagent_platform.legacy_daily_recovery import run_daily_recovery
    from quantagent_platform.legacy_monitor_recovery import run_monitor_recovery
    now = datetime(2026, 10, 3, 8, tzinfo=timezone(timedelta(hours=8)))
    with isolated_engine(root) as (_, engine):
        if operation == "hold":
            with engine.recovery_store.lock(point):
                print("READY", flush=True)
                sys.stdin.readline()
            return
        engine.fetch_market_signals = lambda: {"timestamp": "fixture", "crypto": {"BTC_Price": 60000, "BTC_24h_Chg%": 1, "Fear_Greed": 50}, "macro": {"S&P500_Chg%": 0, "VIX_Volatility": 16}}
        def model(*args, **kwargs):
            if operation == "resume":
                raise AssertionError("research was repeated")
            with (root/"model-effects.log").open("a", encoding="utf-8") as handle: handle.write("call\n")
            if operation in {"infer-daily", "infer-monitor"} and (kwargs.get("use_r1") or operation == "infer-monitor"):
                print("READY", flush=True)
                sys.stdin.readline()
            if operation == "infer-monitor": return '{"sentiment":"中性","weight":"Medium","reason":"合成因子"}'
            return "合成研究" if kwargs.get("use_r1") else json.dumps(daily_payload()["capsule"])
        engine.request_deepseek = model
        def send(text):
            with (root/"send-effects.log").open("a", encoding="utf-8") as handle: handle.write("accepted\n")
            return True
        engine.push_to_wecom = send
        if operation == "infer-monitor":
            class Stop(BaseException): pass
            def stop(seconds): raise Stop()
            engine.fetch_crypto_flash_news = lambda: [news_payload()["news"]]
            try: run_monitor_recovery(replace(engine.monitor_ports(), now=lambda: now, sleep=stop))
            except Stop: pass
            return
        buffer = Path(engine._get_buffer_path("2026-10-03"))
        if operation != "resume" and not buffer.exists():
            buffer.write_text(json.dumps([{"id": "fixture", "fingerprint": "fixture", "title": "合成高权重因子",
                "weight": "High", "sentiment": "中性", "reason": "fixture", "source": "fixture"}]), encoding="utf-8")
        ports = replace(engine.daily_ports(), now=lambda: now, get_buffer_path=lambda: str(buffer))
        if operation == "crash":
            field = {"report": "project_report", "message": "send_message", "memory": "project_memory", "audit": "commit_audit"}[point]
            owned = getattr(ports, field)
            def crash_after_effect(*args):
                result = owned(*args)
                if getattr(result, "status", "succeeded") not in {"succeeded", "confirmed"}:
                    raise AssertionError("effect did not succeed")
                os._exit(23)
            ports = replace(ports, **{field: crash_after_effect})
        print(json.dumps(run_daily_recovery(ports), ensure_ascii=False), flush=True)
