import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import RecipeError, RecipeRunner  # noqa: E402
from quantagent_platform.daily_plugins import (  # noqa: E402
    DAILY_ANALYSIS_CONTRACT,
    DEEPSEEK_CHAT_URL,
    DeepSeekDailyAnalysis,
    JsonDailyContextSource,
    MarkdownDailyReport,
)
from quantagent_platform.plugins import PluginRegistry  # noqa: E402


RECIPE_PATH = ROOT / "recipes" / "offline_daily_research.json"
CONTEXT_FIXTURE = ROOT / "tests" / "fixtures" / "sample_daily_context.json"
ANALYSIS_FIXTURE = ROOT / "tests" / "fixtures" / "sample_daily_analysis.txt"
LIVE_PERMISSIONS = {
    "filesystem:read",
    "filesystem:write",
    "network:https",
    "environment:read-secret",
}


class DailyPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.context = self.root / "context.json"
        self.analysis = self.root / "analysis.txt"
        self.context.write_bytes(CONTEXT_FIXTURE.read_bytes())
        self.analysis.write_bytes(ANALYSIS_FIXTURE.read_bytes())
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)

    def tearDown(self):
        self.temp_dir.cleanup()

    def params(self):
        return {
            "source_path": str(self.context),
            "model_options": {
                "analysis_path": str(self.analysis),
                "max_bytes": 65536,
            },
        }

    def test_offline_recipe_renders_production_compatible_report(self):
        result = RecipeRunner().run(
            self.recipe,
            params=self.params(),
            output_dir=self.output,
            allowed_read_roots=[self.root],
            run_id="offline-daily",
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.final_packet.contract_version, "quantagent.report.v1")
        report = (result.run_dir / "daily_research_report.md").read_text(encoding="utf-8")
        self.assertIn("type: quant-breakfast", report)
        self.assertIn("factors_count_raw: 2", report)
        self.assertIn("factors_count_used: 1", report)
        self.assertIn("[[Bitcoin]]", report)
        self.assertIn("昨日判断审计：中性判断尚未被价格行为证伪。", report)

    def test_offline_mode_rejects_network_model_before_creating_run(self):
        with self.assertRaisesRegex(RecipeError, "network access in offline mode"):
            RecipeRunner().run(
                self.recipe,
                params=self.params(),
                output_dir=self.output,
                allowed_read_roots=[self.root],
                allowed_permissions=LIVE_PERMISSIONS,
                bindings={"model.daily_analysis": "builtin.deepseek-daily-analysis"},
                run_id="offline-denied",
            )
        self.assertFalse((self.output / "offline-denied").exists())

    def test_online_model_requires_explicit_permissions(self):
        with self.assertRaisesRegex(RecipeError, "requires denied permissions"):
            RecipeRunner().run(
                self.recipe,
                params=self.params(),
                output_dir=self.output,
                allowed_read_roots=[self.root],
                bindings={"model.daily_analysis": "builtin.deepseek-daily-analysis"},
                offline=False,
                run_id="permission-denied",
            )
        self.assertFalse((self.output / "permission-denied").exists())

    def test_deepseek_adapter_can_replace_replay_without_leaking_secret(self):
        calls = []

        def fake_post(url, payload, headers, timeout):
            calls.append((url, payload, headers, timeout))
            return {
                "choices": [{"message": {"content": "昨日判断审计：通过。\n今日风险基调：中性。"}}]
            }

        registry = PluginRegistry()
        registry.register(JsonDailyContextSource())
        registry.register(DeepSeekDailyAnalysis(http_post=fake_post))
        registry.register(MarkdownDailyReport())
        runner = RecipeRunner(registry)
        secret = "test-secret-must-not-persist"
        params = self.params()
        params["model_options"] = {
            "api_key_env": "DEEPSEEK_API_KEY",
            "model": "deepseek-v4-pro",
            "timeout_seconds": 30,
        }
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": secret}, clear=False):
            result = runner.run(
                self.recipe,
                params=params,
                output_dir=self.output,
                allowed_read_roots=[self.root],
                allowed_permissions=LIVE_PERMISSIONS,
                bindings={"model.daily_analysis": "builtin.deepseek-daily-analysis"},
                offline=False,
                run_id="deepseek-swap",
            )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], DEEPSEEK_CHAT_URL)
        self.assertEqual(calls[0][1]["model"], "deepseek-v4-pro")
        self.assertEqual(calls[0][2]["Authorization"], f"Bearer {secret}")
        packet_path = result.run_dir / "02-analyze-daily-context.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        self.assertEqual(packet["contract_version"], DAILY_ANALYSIS_CONTRACT)
        self.assertEqual(packet["records"][0]["model"]["provider"], "deepseek")
        persisted = "\n".join(
            path.read_text(encoding="utf-8")
            for path in result.run_dir.iterdir()
            if path.is_file()
        )
        self.assertNotIn(secret, persisted)

    def test_invalid_daily_context_fails_closed(self):
        value = json.loads(self.context.read_text(encoding="utf-8"))
        value["raw_factor_count"] = 0
        self.context.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "raw_factor_count"):
            RecipeRunner().run(
                self.recipe,
                params=self.params(),
                output_dir=self.output,
                allowed_read_roots=[self.root],
                run_id="bad-context",
            )

    def test_empty_replay_analysis_is_rejected(self):
        self.analysis.write_text("  \n", encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "analysis replay text is empty"):
            RecipeRunner().run(
                self.recipe,
                params=self.params(),
                output_dir=self.output,
                allowed_read_roots=[self.root],
                run_id="empty-analysis",
            )


if __name__ == "__main__":
    unittest.main()
