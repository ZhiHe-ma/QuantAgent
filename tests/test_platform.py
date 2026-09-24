import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import ContractError, DataPacket, RecipeError, RecipeRunner  # noqa: E402
from quantagent_platform.builtin_plugins import (  # noqa: E402
    REPORT_CONTRACT,
    SIGNAL_CONTRACT,
)
from quantagent_platform.runner import default_registry  # noqa: E402


RECIPE_PATH = ROOT / "recipes" / "historical_data_health.json"


def signal(signal_id="signal-1"):
    return {
        "signal_id": signal_id,
        "signal_date": "2026-09-20",
        "asset": "BTC",
        "quote_asset": "USDT",
        "bias": "neutral",
        "finalized_at": "2026-09-20T08:00:00+08:00",
    }


class PlatformContractTests(unittest.TestCase):
    def test_packet_is_hash_addressed_and_round_trips(self):
        packet = DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source="test",
            records=[signal()],
        )
        restored = DataPacket.from_dict(packet.to_dict())
        self.assertEqual(restored, packet)
        self.assertEqual(len(packet.content_sha256), 64)

    def test_packet_rejects_naive_creation_timestamp(self):
        with self.assertRaisesRegex(ContractError, "timezone"):
            DataPacket.create(
                contract_version=SIGNAL_CONTRACT,
                packet_type="signal_history",
                source="test",
                records=[signal()],
                created_at="2026-09-20T08:00:00",
            )

    def test_tampered_packet_hash_is_rejected(self):
        packet = DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source="test",
            records=[signal()],
        ).to_dict()
        packet["records"][0]["asset"] = "ETH"
        with self.assertRaisesRegex(ContractError, "content_sha256"):
            DataPacket.from_dict(packet)


class PlatformRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)
        self.runner = RecipeRunner(default_registry())

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_json(self, rows=None):
        path = self.root / "signals.json"
        path.write_text(json.dumps({"signals": rows or [signal()]}), encoding="utf-8")
        return path

    def write_sqlite(self, rows=None):
        path = self.root / "signals.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                """
                CREATE TABLE daily_signals (
                    signal_id TEXT PRIMARY KEY,
                    signal_date TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    quote_asset TEXT NOT NULL,
                    bias TEXT NOT NULL,
                    finalized_at TEXT NOT NULL,
                    watch_items_json TEXT
                )
                """
            )
            for row in rows or [signal()]:
                connection.execute(
                    "INSERT INTO daily_signals VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["signal_id"], row["signal_date"], row["asset"],
                        row["quote_asset"], row["bias"], row["finalized_at"], "[]",
                    ),
                )
            connection.commit()
        return path

    def run_recipe(self, source, path, run_id):
        return self.runner.run(
            self.recipe,
            params={"source_path": str(path), "report_title": "Test report"},
            output_dir=self.output,
            allowed_read_roots=[self.root],
            bindings={"source.signal_history": f"builtin.{source}-signal-source"},
            run_id=run_id,
        )

    def test_same_recipe_swaps_json_and_sqlite_source(self):
        json_result = self.run_recipe("json", self.write_json(), "json-run")
        sqlite_result = self.run_recipe("sqlite", self.write_sqlite(), "sqlite-run")

        self.assertEqual(json_result.status, "completed")
        self.assertEqual(sqlite_result.status, "completed")
        self.assertEqual(json_result.final_packet.contract_version, REPORT_CONTRACT)
        self.assertEqual(sqlite_result.final_packet.contract_version, REPORT_CONTRACT)
        self.assertEqual(
            [step["capability"] for step in json_result.steps],
            [step["capability"] for step in sqlite_result.steps],
        )
        self.assertEqual(json_result.steps[1]["output_sha256"], sqlite_result.steps[1]["output_sha256"])

    def test_run_persists_native_packets_report_and_provenance(self):
        result = self.run_recipe("json", self.write_json(), "audit-run")
        files = {path.name for path in result.run_dir.iterdir()}
        self.assertEqual(
            files,
            {
                "01-load-signal-history.json",
                "02-inspect-data-quality.json",
                "03-write-quality-report.json",
                "data_quality_report.md",
                "run.json",
            },
        )
        run_state = json.loads((result.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run_state["status"], "completed")
        self.assertEqual(len(run_state["steps"]), 3)
        report = (result.run_dir / "data_quality_report.md").read_text(encoding="utf-8")
        self.assertIn("不代表数据真实概率或模型收益", report)
        self.assertIn("not_evaluated", report)
        final_packet = json.loads(
            (result.run_dir / "03-write-quality-report.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(final_packet["records"][0]["artifact_sha256"]), 64)

    def test_quality_flags_missing_duplicates_and_naive_time(self):
        broken = signal()
        broken["asset"] = ""
        broken["finalized_at"] = "2026-09-20T08:00:00"
        path = self.write_json([broken, dict(broken)])
        result = self.run_recipe("json", path, "quality-run")
        quality_packet = json.loads(
            (result.run_dir / "02-inspect-data-quality.json").read_text(encoding="utf-8")
        )
        summary = quality_packet["records"][0]
        self.assertEqual(summary["missing_counts"]["asset"], 2)
        self.assertEqual(summary["duplicate_signal_ids"], ["signal-1"])
        self.assertEqual(len(summary["invalid_timestamps"]), 2)
        self.assertLess(summary["quality_score"], 100)

    def test_source_cannot_read_outside_allowed_root(self):
        path = self.write_json()
        other_root = self.root / "allowed"
        other_root.mkdir()
        with self.assertRaisesRegex(RecipeError, "outside allowed roots"):
            self.runner.run(
                self.recipe,
                params={"source_path": str(path), "report_title": "Test"},
                output_dir=self.output,
                allowed_read_roots=[other_root],
                bindings={"source.signal_history": "builtin.json-signal-source"},
                run_id="denied-run",
            )
        state = json.loads((self.output / "denied-run" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_preflight_rejects_denied_write_permission_before_creating_run(self):
        path = self.write_json()
        with self.assertRaisesRegex(RecipeError, "denied permissions"):
            self.runner.run(
                self.recipe,
                params={"source_path": str(path), "report_title": "Test"},
                output_dir=self.output,
                allowed_read_roots=[self.root],
                bindings={"source.signal_history": "builtin.json-signal-source"},
                allowed_permissions={"filesystem:read"},
                run_id="permission-run",
            )
        self.assertFalse((self.output / "permission-run").exists())

    def test_unknown_plugin_is_rejected_before_creating_run(self):
        with self.assertRaisesRegex(RecipeError, "not installed"):
            self.runner.run(
                self.recipe,
                params={"source_path": str(self.write_json()), "report_title": "Test"},
                output_dir=self.output,
                allowed_read_roots=[self.root],
                bindings={"source.signal_history": "external.unknown"},
                run_id="unknown-run",
            )
        self.assertFalse((self.output / "unknown-run").exists())

    def test_sqlite_source_requires_expected_table(self):
        path = self.root / "empty.sqlite3"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE other (id INTEGER)")
            connection.commit()
        with self.assertRaisesRegex(RecipeError, "no daily_signals table"):
            self.run_recipe("sqlite", path, "bad-sqlite-run")

    def test_catalog_exposes_versions_permissions_and_status(self):
        catalog = default_registry().catalog()
        statuses = {row["plugin_id"]: row["status"] for row in catalog}
        self.assertEqual(statuses["builtin.deepseek-daily-analysis"], "experimental")
        self.assertEqual(statuses["builtin.qlib-factor-research"], "experimental")
        self.assertEqual(statuses["builtin.bt-portfolio-backtest"], "experimental")
        self.assertEqual(statuses["builtin.sec-edgar-source"], "experimental")
        for row in catalog:
            self.assertTrue(row["version"])
            if row["plugin_id"] not in {
                "builtin.deepseek-daily-analysis",
                "builtin.qlib-factor-research",
                "builtin.bt-portfolio-backtest",
                "builtin.sec-edgar-source",
            }:
                self.assertEqual(row["status"], "verified")
            self.assertIn("permissions", row)


if __name__ == "__main__":
    unittest.main()
