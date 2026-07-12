import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
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
        spec = importlib.util.spec_from_file_location("agent_engine_p02_under_test", SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def market_metrics():
    return {
        "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16.0},
        "crypto": {
            "BTC_24h_Chg%": 1.0,
            "BTC_Price": 64000.0,
            "Fear_Greed": 50,
        },
    }


def capsule_json(date):
    return json.dumps(
        {
            "date": date,
            "risk_regime": "neutral",
            "btc_bias": "neutral",
            "confidence": 50,
            "core_thesis": "trusted capsule",
            "invalid_if": "test invalidation",
            "watch_items": ["BTC"],
            "today_check": "test check",
        }
    )


class IdempotencyAndErrorIsolationTests(unittest.TestCase):
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

    def test_memory_rerun_does_not_duplicate_dates(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            initial_state = {
                "last_daily_capsule": {
                    "date": "2026-07-11",
                    "risk_regime": "mixed",
                    "btc_bias": "slightly_bullish",
                    "confidence": 60,
                    "core_thesis": "previous",
                    "invalid_if": "test",
                    "watch_items": [],
                    "today_check": "test",
                },
                "rolling_7d": [
                    {"date": "2026-07-10", "bias": "neutral", "core": "older"},
                    {"date": "2026-07-10", "bias": "bullish", "core": "latest"},
                    {"date": "2026-07-12", "bias": "neutral", "core": "invalid current"},
                ],
            }
            Path(engine.memory_file).write_text(json.dumps(initial_state), encoding="utf-8")
            capsule = json.loads(capsule_json("2026-07-12"))

            self.assertTrue(engine.save_memory_capsule(capsule))
            first_state = json.loads(Path(engine.memory_file).read_text(encoding="utf-8"))

            capsule["core_thesis"] = "same-day replacement"
            self.assertTrue(engine.save_memory_capsule(capsule))
            second_state = json.loads(Path(engine.memory_file).read_text(encoding="utf-8"))

            self.assertEqual(
                [item["date"] for item in first_state["rolling_7d"]],
                ["2026-07-10", "2026-07-11"],
            )
            self.assertEqual(first_state["rolling_7d"], second_state["rolling_7d"])
            self.assertEqual(
                second_state["last_daily_capsule"]["core_thesis"],
                "same-day replacement",
            )

    def test_completed_daily_is_skipped_before_any_external_call(self):
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
            before_report = report_path.read_bytes()
            before_memory = Path(engine.memory_file).read_bytes()
            engine.fetch_market_signals = mock.Mock(
                side_effect=AssertionError("market fetch must be skipped")
            )
            engine.request_deepseek = mock.Mock(
                side_effect=AssertionError("DeepSeek must be skipped")
            )
            engine.push_to_wecom = mock.Mock(
                side_effect=AssertionError("WeCom must be skipped")
            )

            result = engine.run_daily_pipeline()

            self.assertEqual(result, {"status": "skipped", "date": today})
            self.assertEqual(report_path.read_bytes(), before_report)
            self.assertEqual(Path(engine.memory_file).read_bytes(), before_memory)
            engine.fetch_market_signals.assert_not_called()
            engine.request_deepseek.assert_not_called()
            engine.push_to_wecom.assert_not_called()

    def test_dry_run_bypasses_completed_daily_gate_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {"DRY_RUN": "true", "DEEPSEEK_API_KEY": "test-key"},
            clear=True,
        ):
            self.module.BASE_DIR = temp_dir
            daily_dir = Path(temp_dir) / "10_DailyNotes"
            daily_dir.mkdir()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            report_path = daily_dir / f"{today}.md"
            memory_path = daily_dir / "memory_state.json"
            report_path.write_text("existing report", encoding="utf-8")
            memory_path.write_text(
                json.dumps({"last_daily_capsule": {"date": today}, "rolling_7d": []}),
                encoding="utf-8",
            )
            before = {p.name: p.read_bytes() for p in daily_dir.iterdir()}
            engine = self.module.QuantAgent()
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(
                side_effect=["dry analysis", capsule_json(today)]
            )

            result = engine.run_daily_pipeline()

            after = {p.name: p.read_bytes() for p in daily_dir.iterdir()}
            self.assertNotEqual(result.get("status"), "skipped")
            self.assertEqual(engine.request_deepseek.call_count, 2)
            self.assertEqual(before, after)

    def test_force_daily_run_explicitly_bypasses_completed_gate(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "DRY_RUN": "false",
                "FORCE_DAILY_RUN": "true",
                "DEEPSEEK_API_KEY": "test-key",
                "WECOM_WEBHOOK_URL": "https://example.invalid/webhook",
            },
            clear=True,
        ):
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            report_path = Path(engine.daily_dir) / f"{today}.md"
            report_path.write_text("existing report", encoding="utf-8")
            Path(engine.memory_file).write_text(
                json.dumps({"last_daily_capsule": {"date": today}, "rolling_7d": []}),
                encoding="utf-8",
            )
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(
                side_effect=["forced analysis", capsule_json(today)]
            )
            engine.push_to_wecom = mock.Mock()

            result = engine.run_daily_pipeline()

            self.assertNotEqual(result.get("status"), "skipped")
            self.assertEqual(engine.request_deepseek.call_count, 2)
            engine.push_to_wecom.assert_called_once()
            state = json.loads(Path(engine.memory_file).read_text(encoding="utf-8"))
            self.assertEqual(state["rolling_7d"], [])

    def test_request_deepseek_raises_on_invalid_gateway_response(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            response = mock.Mock(status_code=502)
            response.json.return_value = {"error": {"message": "unknown response"}}
            self.module.requests.post = mock.Mock(return_value=response)

            with self.assertRaisesRegex(self.module.DeepSeekError, "缺少choices"):
                engine.request_deepseek("test")

    def test_daily_analysis_failure_has_zero_side_effects(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            memory_path = Path(engine.memory_file)
            memory_path.write_text(
                json.dumps(
                    {
                        "last_daily_capsule": {"date": "2026-07-11"},
                        "rolling_7d": [],
                    }
                ),
                encoding="utf-8",
            )
            before_memory = memory_path.read_bytes()
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(
                side_effect=self.module.DeepSeekError("gateway unavailable")
            )
            engine.push_to_wecom = mock.Mock()

            with self.assertRaises(self.module.DeepSeekError):
                engine.run_daily_pipeline()

            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.assertFalse((Path(engine.daily_dir) / f"{today}.md").exists())
            self.assertEqual(memory_path.read_bytes(), before_memory)
            engine.push_to_wecom.assert_not_called()

    def test_bad_capsule_json_does_not_overwrite_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            memory_path = Path(engine.memory_file)
            memory_path.write_text(
                json.dumps(
                    {
                        "last_daily_capsule": {"date": "2026-07-11"},
                        "rolling_7d": [],
                    }
                ),
                encoding="utf-8",
            )
            before_memory = memory_path.read_bytes()
            engine.fetch_market_signals = mock.Mock(return_value=market_metrics())
            engine.request_deepseek = mock.Mock(side_effect=["trusted analysis", "not-json"])
            engine.push_to_wecom = mock.Mock()

            with self.assertRaisesRegex(self.module.DeepSeekError, "拒绝覆盖Memory"):
                engine.run_daily_pipeline()

            today = self.module.datetime.now().strftime("%Y-%m-%d")
            self.assertTrue((Path(engine.daily_dir) / f"{today}.md").exists())
            self.assertEqual(memory_path.read_bytes(), before_memory)
            engine.push_to_wecom.assert_called_once()

    def test_monitor_parse_failure_is_not_persisted_as_processed(self):
        class StopMonitor(BaseException):
            pass

        with tempfile.TemporaryDirectory() as temp_dir, self.production_env():
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            engine.fetch_crypto_flash_news = mock.Mock(
                return_value=[
                    {
                        "id": "bad-news",
                        "source": "test",
                        "title": "bad response fixture",
                        "body": "fixture",
                        "url": "https://example.invalid/news",
                    }
                ]
            )
            engine.request_deepseek = mock.Mock(return_value="not-json")
            engine._safe_json_write = mock.Mock()

            with mock.patch.object(self.module.time, "sleep", side_effect=StopMonitor):
                with self.assertRaises(StopMonitor):
                    engine.run_monitor_pipeline()

            engine._safe_json_write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
