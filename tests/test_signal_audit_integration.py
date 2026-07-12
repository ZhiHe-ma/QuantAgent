import importlib.util
import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


SOURCE_PATH = Path(__file__).resolve().parents[1] / "agent_engine.py"


def load_agent_module():
    requests_stub = types.ModuleType("requests")
    requests_stub.post = mock.Mock(side_effect=AssertionError("unexpected network call"))
    yfinance_stub = types.ModuleType("yfinance")
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False

    with mock.patch.dict(
        sys.modules,
        {
            "requests": requests_stub,
            "yfinance": yfinance_stub,
            "dotenv": dotenv_stub,
        },
    ):
        spec = importlib.util.spec_from_file_location(
            "agent_engine_signal_audit_under_test", SOURCE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def market_metrics():
    return {
        "timestamp": "2026-07-12 08:00:00",
        "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16.0},
        "crypto": {
            "BTC_24h_Chg%": 1.0,
            "BTC_Price": 64000.0,
            "Fear_Greed": 50,
        },
    }


def capsule(date):
    return {
        "date": date,
        "risk_regime": "neutral",
        "btc_bias": "slightly_bullish",
        "confidence": 70,
        "core_thesis": "trusted capsule",
        "invalid_if": "test invalidation",
        "watch_items": ["BTC"],
        "today_check": "test check",
    }


class SignalAuditIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_agent_module()

    def production_env(self):
        return mock.patch.dict(
            os.environ,
            {
                "DRY_RUN": "false",
                "DEEPSEEK_API_KEY": "test-key",
                "WECOM_WEBHOOK_URL": "https://example.invalid/webhook",
            },
            clear=True,
        )

    def configure_successful_pipeline(self, engine, today):
        engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
        engine.request_deepseek = mock.Mock(
            side_effect=["analysis", json.dumps(capsule(today))]
        )
        engine.push_to_wecom = mock.Mock(return_value=True)

    def test_production_records_completed_signal_after_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.configure_successful_pipeline(engine, today)

            result = engine.run_daily_pipeline()

            canonical = engine.signal_audit_store.get_canonical_signal(today)
            self.assertEqual(result["audit"]["status"], "recorded")
            self.assertEqual(canonical["signal_date"], today)
            self.assertEqual(canonical["asset"], "BTC")
            self.assertEqual(canonical["confidence_raw"], 70)
            self.assertEqual(canonical["reference_price"], 64000.0)
            with closing(sqlite3.connect(engine.signal_audit_file)) as connection:
                wecom_sent = connection.execute(
                    "SELECT wecom_sent FROM audit_runs"
                ).fetchone()[0]
            self.assertEqual(wecom_sent, 1)
            self.assertTrue(Path(engine.memory_file).exists())
            self.assertTrue(Path(engine.signal_audit_file).exists())

    def test_wecom_business_result_controls_delivery_truth(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            response = mock.Mock(status_code=200)
            response.json.return_value = {"errcode": 93000, "errmsg": "invalid webhook"}
            self.module.requests.post = mock.Mock(return_value=response)
            self.assertFalse(engine.push_to_wecom("message"))

            response.json.return_value = {"errcode": 0, "errmsg": "ok"}
            self.assertTrue(engine.push_to_wecom("message"))

    def test_unconfirmed_wecom_delivery_is_recorded_as_false(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.configure_successful_pipeline(engine, today)
            engine.push_to_wecom.return_value = False

            result = engine.run_daily_pipeline()

            self.assertEqual(result["audit"]["status"], "recorded")
            with closing(sqlite3.connect(engine.signal_audit_file)) as connection:
                wecom_sent = connection.execute(
                    "SELECT wecom_sent FROM audit_runs"
                ).fetchone()[0]
            self.assertEqual(wecom_sent, 0)

    def test_dry_run_previews_audit_without_database_or_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"DRY_RUN": "true", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.configure_successful_pipeline(engine, today)

            result = engine.run_daily_pipeline()

            self.assertEqual(result["audit"]["status"], "dry_run")
            self.assertFalse(Path(engine.signal_audit_file).exists())
            self.assertFalse(Path(engine.daily_dir).exists())
            engine.push_to_wecom.assert_not_called()

    def test_audit_failure_does_not_destroy_delivered_report_or_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.configure_successful_pipeline(engine, today)
            engine.signal_audit_store.record_completed_signal = mock.Mock(
                side_effect=self.module.SignalAuditError("database unavailable")
            )

            result = engine.run_daily_pipeline()

            self.assertEqual(result["audit"]["status"], "failed")
            self.assertTrue((Path(engine.daily_dir) / f"{today}.md").exists())
            self.assertTrue(Path(engine.memory_file).exists())
            engine.push_to_wecom.assert_called_once()

    def test_real_connection_failure_is_isolated_after_memory_delivery(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.configure_successful_pipeline(engine, today)
            real_connect = engine.signal_audit_store._connect
            calls = 0

            def fail_second_connection():
                nonlocal calls
                calls += 1
                if calls == 1:
                    return real_connect()
                raise sqlite3.OperationalError("audit connection unavailable")

            with mock.patch.object(
                engine.signal_audit_store,
                "_connect",
                side_effect=fail_second_connection,
            ):
                result = engine.run_daily_pipeline()

            self.assertEqual(result["audit"]["status"], "failed")
            self.assertTrue((Path(engine.daily_dir) / f"{today}.md").exists())
            self.assertTrue(Path(engine.memory_file).exists())
            engine.push_to_wecom.assert_called_once()

    def test_delivery_capsule_memory_audit_order_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            events = []
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(return_value="analysis")
            engine.push_to_wecom = mock.Mock(
                side_effect=lambda *_: events.append("wecom") or True
            )
            engine.generate_memory_capsule = mock.Mock(
                side_effect=lambda *_: events.append("capsule") or capsule(today)
            )
            engine.save_memory_capsule = mock.Mock(
                side_effect=lambda *_: events.append("memory") or True
            )
            engine.record_signal_audit = mock.Mock(
                side_effect=lambda *_: events.append("audit") or {"status": "recorded"}
            )

            engine.run_daily_pipeline()

            self.assertEqual(events, ["wecom", "capsule", "memory", "audit"])

    def test_memory_failure_skips_audit_persistence(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(return_value="analysis")
            engine.push_to_wecom = mock.Mock()
            engine.generate_memory_capsule = mock.Mock(return_value=capsule(today))
            engine.save_memory_capsule = mock.Mock(return_value=False)
            engine.record_signal_audit = mock.Mock()

            result = engine.run_daily_pipeline()

            self.assertEqual(
                result["audit"],
                {"status": "skipped", "reason": "memory_not_saved"},
            )
            engine.record_signal_audit.assert_not_called()

    def test_completed_daily_skip_does_not_touch_audit_database(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            report_path = Path(engine.daily_dir) / f"{today}.md"
            report_path.write_text("existing report", encoding="utf-8")
            Path(engine.memory_file).write_text(
                json.dumps(
                    {
                        "last_daily_capsule": {"date": today},
                        "rolling_7d": [],
                    }
                ),
                encoding="utf-8",
            )
            engine.record_signal_audit = mock.Mock(
                side_effect=AssertionError("audit must be skipped")
            )

            result = engine.run_daily_pipeline()

            self.assertEqual(result, {"status": "skipped", "date": today})
            engine.record_signal_audit.assert_not_called()
            self.assertFalse(Path(engine.signal_audit_file).exists())


if __name__ == "__main__":
    unittest.main()
