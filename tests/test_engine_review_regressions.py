"""Offline regression coverage for the five agent engine review findings."""

import contextlib
import importlib.util
import io
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


SOURCE_PATH = Path(__file__).resolve().parents[1] / "agent_engine.py"


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 9, 25, 8, 0, 0)
        return value if tz is None else value.astimezone(tz)


class StopMonitor(BaseException):
    pass


def load_engine():
    requests = types.ModuleType("requests")
    requests.post = mock.Mock(side_effect=AssertionError("unexpected network"))
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *_args, **_kwargs: False
    with mock.patch.dict(sys.modules, {
        "requests": requests,
        "yfinance": types.ModuleType("yfinance"),
        "dotenv": dotenv,
    }):
        spec = importlib.util.spec_from_file_location("engine_review_under_test", SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    module.datetime = FixedClock
    return module


def capsule():
    return {
        "date": "2026-09-25",
        "risk_regime": "neutral",
        "btc_bias": "neutral",
        "confidence": 50,
        "core_thesis": "valid thesis",
        "invalid_if": "valid invalidation",
        "watch_items": ["BTC"],
        "today_check": "valid check",
    }


def news(identifier, time="07:00:00", **extra):
    return {
        "id": identifier,
        "fingerprint": "fp-" + identifier,
        "time": time,
        "source": "fixture",
        "title": identifier,
        "body": identifier,
        "weight": "High",
        "sentiment": "利多",
        "reason": "valid fixture",
        "url": "https://example.invalid/" + identifier,
        **extra,
    }


class EngineReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.enterContext(mock.patch.dict(os.environ, {
            "DRY_RUN": "false",
            "DEEPSEEK_API_KEY": "test-key",
            "WECOM_WEBHOOK_URL": "https://example.invalid/webhook",
        }, clear=True))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.module = load_engine()
        self.module.BASE_DIR = temp.name
        self.engine = self.module.QuantAgent()

    def write_buffer(self, date, factors):
        Path(self.engine._get_buffer_path(date)).write_text(
            json.dumps(factors), encoding="utf-8"
        )

    def configure_daily(self, generated=None):
        self.engine.fetch_market_signals = mock.Mock(return_value={
            "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16.0},
            "crypto": {"BTC_Price": 64000.0, "BTC_24h_Chg%": 1.0, "Fear_Greed": 50},
        })
        self.engine.request_deepseek = mock.Mock(side_effect=[
            "valid analysis", json.dumps(capsule() if generated is None else generated)
        ])
        self.engine.push_to_wecom = mock.Mock(return_value=True)

    def model_factors(self):
        prompt = json.loads(self.engine.request_deepseek.call_args_list[0].kwargs["prompt"])
        return prompt["24h_high_value_news_factors"]

    def test_daily_uses_rolling_24_hours_with_legacy_buffer_times(self):
        self.write_buffer("2026-09-24", [
            news("outside", "07:59:59"), news("boundary", "08:00:00"),
            news("yesterday", "09:00:00"),
        ])
        self.write_buffer("2026-09-25", [
            news("today"), news("future", "08:00:01"),
            news("unknown-time", "invalid"),
        ])
        self.configure_daily()
        self.engine.run_daily_pipeline()
        self.assertEqual(
            {factor["title"] for factor in self.model_factors()},
            {"boundary", "yesterday", "today"},
        )

    def test_daily_filters_publication_times_and_preserves_observation_fallback(self):
        utc_publication = datetime(2026, 9, 25, 7).astimezone(timezone.utc).isoformat()
        self.write_buffer("2026-09-25", [
            news("old-publication", published="2026-09-23T12:00:00"),
            news("future-publication", published="2026-09-25T09:00:00"),
            news("utc-publication", published=utc_publication),
            news("observation-fallback", time="invalid", published="invalid",
                 observed_at="2026-09-25T07:30:00"),
        ])
        self.configure_daily()
        self.engine.run_daily_pipeline()
        self.assertEqual(
            {factor["title"] for factor in self.model_factors()},
            {"utc-publication", "observation-fallback"},
        )

    def test_daily_deduplicates_news_across_buffers(self):
        self.write_buffer("2026-09-24", [news("same", "23:00:00")])
        self.write_buffer("2026-09-25", [news("same")])
        self.configure_daily()
        self.engine.run_daily_pipeline()
        self.assertEqual([factor["title"] for factor in self.model_factors()], ["same"])

    def assert_monitor_recovers(self, failed_file, repeat_news=True):
        first = news("news-a")
        engine = self.engine
        if failed_file == "quarantine":
            Path(engine.failed_news_file).write_text(json.dumps({
                engine._news_fingerprint(first): {"attempts": 1, "status": "retry_pending"}
            }), encoding="utf-8")
        target = {
            "buffer": engine._get_buffer_path(), "dedup": engine.dedup_file,
            "fingerprint": engine.fingerprint_file, "quarantine": engine.failed_news_file,
        }[failed_file]
        engine.fetch_crypto_flash_news = mock.Mock(side_effect=[
            [first], [first] if repeat_news else [], StopMonitor(),
        ])
        engine.request_deepseek = mock.Mock(return_value=json.dumps({
            "sentiment": "利多", "weight": "High", "reason": "valid fixture",
        }))
        real_write = engine._safe_json_write
        failed = False

        def write_with_one_failure(path, data):
            nonlocal failed
            if path == target and not failed:
                failed = True
                raise PermissionError("injected transient write failure")
            return real_write(path, data)

        with mock.patch.object(engine, "_safe_json_write", side_effect=write_with_one_failure), \
                mock.patch.object(self.module.time, "sleep", return_value=None):
            with self.assertRaises(StopMonitor):
                engine.run_monitor_pipeline()
        self.assertTrue(failed, "fault was not injected")
        for path in (engine._get_buffer_path(), engine.dedup_file, engine.fingerprint_file):
            self.assertTrue(Path(path).exists(), path)
        factors = json.loads(Path(engine._get_buffer_path()).read_text(encoding="utf-8"))
        self.assertEqual([item["id"] for item in factors], ["news-a"])
        self.assertEqual(
            sorted(json.loads(Path(engine.dedup_file).read_text(encoding="utf-8"))),
            ["news-a"],
        )
        self.assertEqual(len(json.loads(Path(engine.fingerprint_file).read_text(encoding="utf-8"))), 1)

    def test_monitor_retries_after_buffer_write_failure(self):
        self.assert_monitor_recovers("buffer")

    def test_monitor_retries_after_dedup_write_failure(self):
        self.assert_monitor_recovers("dedup")

    def test_monitor_retries_after_fingerprint_write_failure(self):
        self.assert_monitor_recovers("fingerprint")

    def test_monitor_retries_after_quarantine_write_failure(self):
        self.assert_monitor_recovers("quarantine")

    def test_monitor_flushes_failed_batch_when_news_leaves_feed(self):
        self.assert_monitor_recovers("buffer", repeat_news=False)

    def test_monitor_persists_timezone_aware_observation_time(self):
        self.engine.fetch_crypto_flash_news = mock.Mock(side_effect=[[news("news-a")], StopMonitor()])
        self.engine.request_deepseek = mock.Mock(return_value=json.dumps({
            "sentiment": "利多", "weight": "High", "reason": "valid fixture",
        }))
        with mock.patch.object(self.module.time, "sleep", return_value=None):
            with self.assertRaises(StopMonitor):
                self.engine.run_monitor_pipeline()
        factor = json.loads(Path(self.engine._get_buffer_path()).read_text(encoding="utf-8"))[0]
        self.assertIn("observed_at", factor)
        self.assertIsNotNone(datetime.fromisoformat(factor["observed_at"]).utcoffset())

    def test_gateway_rejects_incomplete_and_unknown_finish_reasons(self):
        for reason in ("length", "insufficient_system_resource", "content_filter", "aborted", "tool_calls", "unknown", None):
            with self.subTest(reason=reason):
                response = mock.Mock(status_code=200)
                response.json.return_value = {"choices": [{
                    "finish_reason": reason, "message": {"content": "partial analysis"},
                }]}
                self.module.requests.post = mock.Mock(return_value=response)
                with self.assertRaises(self.module.DeepSeekError):
                    self.engine.request_deepseek("fixture")

    def test_gateway_accepts_normal_completion(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {"choices": [{
            "finish_reason": "stop", "message": {"content": " valid analysis "},
        }]}
        self.module.requests.post = mock.Mock(return_value=response)
        self.assertEqual(self.engine.request_deepseek("fixture"), "valid analysis")

    def test_capsule_rejects_empty_or_nontext_required_fields(self):
        for field in ("core_thesis", "invalid_if", "today_check"):
            for value in (None, "", " \n ", [], {}, 7):
                with self.subTest(field=field, value=value):
                    invalid = {**capsule(), field: value}
                    self.engine.request_deepseek = mock.Mock(return_value=json.dumps(invalid))
                    with self.assertRaises(self.module.DeepSeekError):
                        self.engine.generate_memory_capsule("2026-09-25", "analysis", {}, [])

    def test_capsule_rejects_invalid_watch_items(self):
        for value in ([None], [""], [" \n"], [{}], [7]):
            with self.subTest(value=value):
                self.engine.request_deepseek = mock.Mock(return_value=json.dumps({
                    **capsule(), "watch_items": value,
                }))
                with self.assertRaises(self.module.DeepSeekError):
                    self.engine.generate_memory_capsule("2026-09-25", "analysis", {}, [])

    def test_invalid_capsule_keeps_previous_memory_and_allows_retry(self):
        previous = {"last_daily_capsule": {**capsule(), "date": "2026-09-24"}, "rolling_7d": []}
        path = Path(self.engine.memory_file)
        path.write_text(json.dumps(previous), encoding="utf-8")
        before = path.read_bytes()
        self.configure_daily({**capsule(), "core_thesis": None})
        with self.assertRaises(self.module.DeepSeekError):
            self.engine.run_daily_pipeline()
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(Path(self.engine.signal_audit_file).exists())
        self.configure_daily()
        result = self.engine.run_daily_pipeline()
        self.assertEqual(result["audit"]["status"], "recorded")

    def test_audit_preserves_selected_factor_provenance(self):
        factor = news("source-news", published="2026-09-25T07:00:00",
                      observed_at="2026-09-25T07:05:00", calibrated_from="Critical",
                      calibration_reason="calibrated fixture")
        self.write_buffer("2026-09-25", [factor])
        self.configure_daily()
        self.engine.run_daily_pipeline()
        with contextlib.closing(sqlite3.connect(self.engine.signal_audit_file)) as connection:
            fingerprint, raw = connection.execute("SELECT fingerprint, raw_json FROM signal_factors").fetchone()
        self.assertEqual(fingerprint, "fp-source-news")
        raw_factor = json.loads(raw)
        for key in ("id", "fingerprint", "url", "published", "observed_at", "calibrated_from", "calibration_reason"):
            self.assertEqual(raw_factor.get(key), factor[key], key)


if __name__ == "__main__":
    unittest.main()
