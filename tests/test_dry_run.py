import contextlib
import importlib.util
import io
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
    """Load the engine without installing its production-only dependencies."""
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
        spec = importlib.util.spec_from_file_location("agent_engine_under_test", SOURCE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class DryRunIsolationTests(unittest.TestCase):
    def setUp(self):
        self.module = load_agent_module()
        self.env = mock.patch.dict(
            os.environ,
            {
                "DRY_RUN": "true",
                "DEEPSEEK_API_KEY": "test-key",
            },
            clear=True,
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_constructor_does_not_create_daily_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.module.BASE_DIR = temp_dir
            expected_dir = Path(temp_dir) / "10_DailyNotes"

            engine = self.module.QuantAgent()

            self.assertTrue(engine.dry_run)
            self.assertFalse(expected_dir.exists())

    def test_daily_pipeline_reads_inputs_and_leaves_all_files_unchanged(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.module.BASE_DIR = temp_dir
            daily_dir = Path(temp_dir) / "10_DailyNotes"
            daily_dir.mkdir()

            today = self.module.datetime.now().strftime("%Y-%m-%d")
            buffer_path = daily_dir / f"{today}_news_buffer.json"
            memory_path = daily_dir / "memory_state.json"
            buffer_path.write_text(
                json.dumps(
                    [
                        {
                            "id": "n1",
                            "title": "ETF approved",
                            "body": "Approval text",
                            "weight": "High",
                            "reason": "direct catalyst",
                            "time": "2026-07-11T00:00:00Z",
                            "source": "test",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            original_memory = {
                "last_daily_capsule": {
                    "date": "2026-07-10",
                    "risk_regime": "mixed",
                    "btc_bias": "neutral",
                    "confidence": 50,
                    "core_thesis": "existing state",
                    "invalid_if": "invalidated",
                    "watch_items": [],
                    "today_check": "check",
                },
                "rolling_7d": [],
            }
            memory_path.write_text(json.dumps(original_memory), encoding="utf-8")

            before = {
                path.name: path.read_bytes()
                for path in daily_dir.iterdir()
                if path.is_file()
            }

            engine = self.module.QuantAgent()
            engine.fetch_market_signals = mock.Mock(
                return_value={
                    "macro": {"S&P500_Chg%": 1.25, "VIX_Volatility": 15.5},
                    "crypto": {
                        "BTC_24h_Chg%": 2.5,
                        "BTC_Price": 65000.0,
                        "Fear_Greed": 55,
                    },
                }
            )
            engine.request_deepseek = mock.Mock(
                side_effect=[
                    "昨日判断审计：通过。\n今日风险基调：中性。",
                    json.dumps(
                        {
                            "date": today,
                            "risk_regime": "neutral",
                            "btc_bias": "neutral",
                            "confidence": 50,
                            "core_thesis": "test capsule",
                            "invalid_if": "test invalidation",
                            "watch_items": ["BTC"],
                            "today_check": "test check",
                        }
                    ),
                ]
            )
            engine.push_to_wecom = mock.Mock(
                side_effect=AssertionError("Daily pipeline must not call WeCom in dry-run")
            )

            real_open = open

            def read_only_open(file, mode="r", *args, **kwargs):
                if any(flag in mode for flag in ("w", "a", "x", "+")):
                    raise AssertionError(f"unexpected file write in dry-run: {file} ({mode})")
                return real_open(file, mode, *args, **kwargs)

            output = io.StringIO()
            with (
                contextlib.redirect_stdout(output),
                mock.patch("builtins.open", side_effect=read_only_open),
                mock.patch.object(
                    self.module.os,
                    "replace",
                    side_effect=AssertionError("unexpected atomic replace in dry-run"),
                ),
            ):
                result = engine.run_daily_pipeline()

            after = {
                path.name: path.read_bytes()
                for path in daily_dir.iterdir()
                if path.is_file()
            }
            self.assertEqual(before, after)
            self.assertFalse((daily_dir / f"{today}.md").exists())
            engine.push_to_wecom.assert_not_called()
            self.assertEqual(engine.request_deepseek.call_count, 2)
            self.assertEqual(result["capsule"]["date"], today)
            self.assertIn("日报预览开始", output.getvalue())
            self.assertIn("Memory Capsule 预览", output.getvalue())

    def test_generate_memory_capsule_never_persists_by_itself(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            engine.request_deepseek = mock.Mock(
                return_value=json.dumps(
                    {
                        "risk_regime": "mixed",
                        "btc_bias": "slightly_bullish",
                        "confidence": 65,
                        "core_thesis": "generated only",
                        "invalid_if": "test",
                        "watch_items": [],
                        "today_check": "test",
                    }
                )
            )

            capsule = engine.generate_memory_capsule(
                "2026-07-11", "analysis", {"metric": 1}, []
            )

            self.assertEqual(capsule["date"], "2026-07-11")
            self.assertFalse(Path(engine.memory_file).exists())

    def test_central_write_and_wecom_guards_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            target = Path(temp_dir) / "blocked.json"

            wrote = engine._safe_json_write(str(target), {"must": "not exist"})
            engine.wecom_url = "https://example.invalid/webhook"
            engine.push_to_wecom("blocked message")

            self.assertFalse(wrote)
            self.assertFalse(target.exists())
            self.module.requests.post.assert_not_called()

    def test_production_pipeline_still_persists_at_pipeline_boundary(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.dict(
            os.environ,
            {
                "DRY_RUN": "false",
                "DEEPSEEK_API_KEY": "test-key",
                "WECOM_WEBHOOK_URL": "https://example.invalid/webhook",
            },
            clear=True,
        ):
            self.module.BASE_DIR = temp_dir
            engine = self.module.QuantAgent()
            today = self.module.datetime.now().strftime("%Y-%m-%d")
            engine.fetch_market_signals = mock.Mock(
                return_value={
                    "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16.0},
                    "crypto": {
                        "BTC_24h_Chg%": 1.0,
                        "BTC_Price": 64000.0,
                        "Fear_Greed": 50,
                    },
                }
            )
            engine.request_deepseek = mock.Mock(
                side_effect=[
                    "production analysis",
                    json.dumps(
                        {
                            "risk_regime": "neutral",
                            "btc_bias": "neutral",
                            "confidence": 50,
                            "core_thesis": "production capsule",
                            "invalid_if": "test",
                            "watch_items": [],
                            "today_check": "test",
                        }
                    ),
                ]
            )
            engine.push_to_wecom = mock.Mock()

            engine.run_daily_pipeline()

            report_path = Path(engine.daily_dir) / f"{today}.md"
            memory_path = Path(engine.memory_file)
            self.assertTrue(report_path.exists())
            self.assertTrue(memory_path.exists())
            engine.push_to_wecom.assert_called_once()
            state = json.loads(memory_path.read_text(encoding="utf-8"))
            self.assertEqual(state["last_daily_capsule"]["date"], today)


if __name__ == "__main__":
    unittest.main()
