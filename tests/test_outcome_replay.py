import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import DataPacket, RecipeError, RecipeRunner  # noqa: E402
from quantagent_platform.builtin_plugins import SIGNAL_CONTRACT  # noqa: E402
from quantagent_platform.outcome_plugins import OUTCOME_CONTRACT  # noqa: E402
from signal_audit import SignalAuditStore  # noqa: E402


RECIPE_PATH = ROOT / "recipes" / "offline_outcome_backfill.json"
MIGRATIONS = ROOT / "sql"
PRICE_FIXTURE = ROOT / "tests" / "fixtures" / "sample_prices.json"


def run_record():
    return {
        "run_id": "legacy-run-1",
        "trade_date": "2026-09-20",
        "started_at": "2026-09-20T07:59:00+08:00",
        "completed_at": "2026-09-20T08:01:00+08:00",
        "run_kind": "scheduled",
        "code_version": "test",
        "source_sha256": "fixture",
        "fast_model": "fixture-fast",
        "reason_model": "fixture-reason",
        "report_written": True,
        "wecom_sent": False,
        "memory_saved": True,
    }


def audit_signal():
    return {
        "signal_id": "signal-btc-1",
        "signal_date": "2026-09-20",
        "asset": "BTC",
        "quote_asset": "USDT",
        "decision_horizon": "1d",
        "risk_regime": "neutral",
        "bias": "bullish",
        "confidence_raw": 70,
        "confidence_calibrated": None,
        "core_thesis": "fixture",
        "invalid_if": "fixture",
        "today_check": "fixture",
        "watch_items": [],
        "reference_price": 100.0,
        "market_snapshot": {},
        "previous_memory": {},
        "analysis_text": "fixture",
        "data_quality_score": 100,
        "quality_flags": [],
        "finalized_at": "2026-09-20T08:01:00+08:00",
    }


def replay_signal(include_decision_at=True):
    record = {
        "signal_id": "signal-btc-1",
        "signal_date": "2026-09-20",
        "asset": "BTC",
        "quote_asset": "USDT",
        "bias": "bullish",
        "reference_price": 100.0,
        "finalized_at": "2026-09-20T08:01:00+08:00",
    }
    if include_decision_at:
        record["decision_at"] = "2026-09-20T08:00:00+08:00"
    return record


class OfflineReplayOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)
        self.runner = RecipeRunner()
        self.database = self.root / "signal_audit.sqlite3"
        SignalAuditStore(self.database, MIGRATIONS).record_completed_signal(
            run_record(), audit_signal(), []
        )
        self.prices = self.root / "prices.json"
        self.prices.write_text(PRICE_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_packet(self, include_decision_at=True):
        packet = DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source="test.fixture",
            records=[replay_signal(include_decision_at)],
            created_at="2026-09-20T08:02:00+08:00",
            metadata={"fixture": True},
        )
        path = self.root / "signal_packet.json"
        path.write_text(json.dumps(packet.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def run_recipe(self, run_id, apply, packet_path=None, write_roots=None):
        if write_roots is None:
            write_roots = [self.root]
        return self.runner.run(
            self.recipe,
            params={
                "source_path": str(packet_path or self.write_packet()),
                "prices_path": str(self.prices),
                "target_database_path": str(self.database),
                "apply_backfill": apply,
                "horizon_hours": [24, 72, 168],
                "max_observation_delay_hours": 1,
                "neutral_band_decimal": 0.002,
                "report_title": "Outcome fixture report",
            },
            output_dir=self.output,
            allowed_read_roots=[self.root],
            allowed_write_roots=write_roots,
            bindings={"source.signal_history": "builtin.packet-replay-source"},
            run_id=run_id,
        )

    def outcome_count(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute("SELECT COUNT(*) FROM signal_outcomes").fetchone()[0]

    def test_preview_evaluates_without_writing_database(self):
        result = self.run_recipe("preview-run", False)
        self.assertEqual(result.status, "completed")
        self.assertEqual(self.outcome_count(), 0)
        packet = json.loads(
            (result.run_dir / "03-backfill-outcome-database.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["contract_version"], OUTCOME_CONTRACT)
        self.assertEqual(packet["metadata"]["backfill_receipt"]["status"], "preview")
        self.assertEqual(packet["metadata"]["backfill_receipt"]["evaluated"], 3)
        report = (result.run_dir / "outcome_report.md").read_text(encoding="utf-8")
        self.assertIn("数据库回填: `preview`", report)
        self.assertIn("不联网、不调用模型、不发送消息", report)

    def test_apply_backfills_three_horizons_with_explicit_unit_conversion(self):
        result = self.run_recipe("apply-run", True)
        self.assertEqual(self.outcome_count(), 3)
        with closing(sqlite3.connect(self.database)) as connection:
            rows = connection.execute(
                "SELECT horizon_hours, return_pct, direction_correct FROM signal_outcomes ORDER BY horizon_hours"
            ).fetchall()
        self.assertEqual(rows, [(24, 5.0, 1), (72, -5.0, 0), (168, 10.0, 1)])
        packet = json.loads(
            (result.run_dir / "03-backfill-outcome-database.json").read_text(encoding="utf-8")
        )
        receipt = packet["metadata"]["backfill_receipt"]
        self.assertEqual((receipt["status"], receipt["inserted"], receipt["existing"]), ("applied", 3, 0))
        self.assertEqual(packet["metadata"]["return_unit"], "decimal")

    def test_repeat_apply_is_idempotent(self):
        packet_path = self.write_packet()
        self.run_recipe("first-apply", True, packet_path=packet_path)
        result = self.run_recipe("second-apply", True, packet_path=packet_path)
        self.assertEqual(self.outcome_count(), 3)
        packet = json.loads(
            (result.run_dir / "03-backfill-outcome-database.json").read_text(encoding="utf-8")
        )
        receipt = packet["metadata"]["backfill_receipt"]
        self.assertEqual((receipt["inserted"], receipt["existing"]), (0, 3))

    def test_conflicting_existing_outcome_rolls_back(self):
        packet_path = self.write_packet()
        self.run_recipe("first-conflict", True, packet_path=packet_path)
        changed = json.loads(self.prices.read_text(encoding="utf-8"))
        changed["observations"][1]["price"] = 106.0
        self.prices.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "conflicting outcome"):
            self.run_recipe("second-conflict", True, packet_path=packet_path)
        self.assertEqual(self.outcome_count(), 3)
        state = json.loads((self.output / "second-conflict" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_missing_decision_at_is_not_replaced_with_finalized_at(self):
        result = self.run_recipe(
            "missing-decision", True, packet_path=self.write_packet(include_decision_at=False)
        )
        self.assertEqual(self.outcome_count(), 0)
        packet = json.loads(
            (result.run_dir / "02-evaluate-signal-outcomes.json").read_text(encoding="utf-8")
        )
        self.assertEqual({row["reason"] for row in packet["records"]}, {"missing_decision_at"})
        self.assertEqual(packet["metadata"]["not_evaluable_count"], 3)

    def test_tampered_replay_packet_is_rejected(self):
        packet_path = self.write_packet()
        value = json.loads(packet_path.read_text(encoding="utf-8"))
        value["records"][0]["reference_price"] = 1.0
        packet_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "integrity validation"):
            self.run_recipe("tampered-run", False, packet_path=packet_path)

    def test_apply_requires_explicit_write_root(self):
        denied = self.root / "output-only"
        denied.mkdir()
        with self.assertRaisesRegex(RecipeError, "outside allowed roots"):
            self.run_recipe("write-denied", True, write_roots=[denied])
        self.assertEqual(self.outcome_count(), 0)

    def test_apply_has_no_implicit_write_root(self):
        with self.assertRaisesRegex(RecipeError, "outside allowed roots"):
            self.runner.run(
                self.recipe,
                params={
                    "source_path": str(self.write_packet()),
                    "prices_path": str(self.prices),
                    "target_database_path": str(self.database),
                    "apply_backfill": True,
                    "horizon_hours": [24, 72, 168],
                    "max_observation_delay_hours": 1,
                    "neutral_band_decimal": 0.002,
                    "report_title": "Outcome fixture report",
                },
                output_dir=self.output,
                allowed_read_roots=[self.root],
                bindings={"source.signal_history": "builtin.packet-replay-source"},
                run_id="missing-write-root",
            )
        self.assertEqual(self.outcome_count(), 0)


if __name__ == "__main__":
    unittest.main()
