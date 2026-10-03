"""Synthetic recovery inputs; never imports test cases or contacts providers."""
from typing import Any


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
