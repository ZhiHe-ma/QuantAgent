import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_audit import (  # noqa: E402
    SignalAuditError,
    SignalAuditStore,
    SignalAuditValidationError,
    calculate_data_quality,
)


MIGRATIONS = ROOT / "sql"


def run_record(run_id="run-1", run_kind="scheduled"):
    return {
        "run_id": run_id,
        "trade_date": "2026-07-12",
        "started_at": "2026-07-12T08:00:00+08:00",
        "completed_at": "2026-07-12T08:01:00+08:00",
        "run_kind": run_kind,
        "code_version": "v5.2",
        "source_sha256": "abc",
        "fast_model": "flash",
        "reason_model": "pro",
        "report_written": True,
        "wecom_sent": True,
        "memory_saved": True,
    }


def signal_record(signal_id="signal-1"):
    return {
        "signal_id": signal_id,
        "signal_date": "2026-07-12",
        "asset": "BTC",
        "quote_asset": "USDT",
        "decision_horizon": "1d",
        "risk_regime": "mixed",
        "bias": "slightly_bullish",
        "confidence_raw": 70,
        "confidence_calibrated": None,
        "core_thesis": "test thesis",
        "invalid_if": "test invalidation",
        "today_check": "test check",
        "watch_items": ["BTC 64k"],
        "reference_price": 64000,
        "market_snapshot": {
            "crypto": {"BTC_Price": 64000, "Fear_Greed": 50},
            "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16},
        },
        "previous_memory": {},
        "analysis_text": "analysis",
        "data_quality_score": 100,
        "quality_flags": [],
        "finalized_at": "2026-07-12T08:01:00+08:00",
    }


def factors():
    return [
        {
            "time": "07:00:00",
            "source": "rss",
            "title": "factor",
            "sentiment": "利多",
            "weight": "High",
            "reason": "reason",
        }
    ]


class SignalAuditStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "runtime" / "signal_audit.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def store(self, dry_run=False):
        return SignalAuditStore(self.db_path, MIGRATIONS, dry_run=dry_run)

    def test_constructor_has_no_filesystem_side_effect(self):
        self.store()
        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.db_path.parent.exists())

    def test_dry_run_never_creates_or_opens_database(self):
        store = self.store(dry_run=True)
        self.assertEqual(store.initialize()["status"], "dry_run")
        result = store.record_completed_signal(run_record(), signal_record(), factors())
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(self.db_path.exists())
        self.assertFalse(self.db_path.parent.exists())

    def test_migrations_are_idempotent(self):
        store = self.store()
        store.initialize()
        store.initialize()
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(
                "SELECT version, name FROM schema_migrations"
            ).fetchall()
        self.assertEqual(rows, [(1, "initial_signal_audit")])

    def test_initialize_wraps_directory_creation_failure(self):
        store = self.store()
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(SignalAuditError, "failed to initialize"):
                store.initialize()

    def test_initialize_and_read_release_database_file_handle(self):
        store = self.store()
        store.initialize()
        moved_path = self.db_path.with_suffix(".moved")
        self.db_path.replace(moved_path)
        moved_path.replace(self.db_path)

        store.record_completed_signal(run_record(), signal_record(), factors())
        self.assertIsNotNone(store.get_canonical_signal("2026-07-12"))
        self.db_path.replace(moved_path)
        moved_path.replace(self.db_path)

    def test_records_signal_and_reads_canonical(self):
        store = self.store()
        result = store.record_completed_signal(run_record(), signal_record(), factors())
        canonical = store.get_canonical_signal("2026-07-12")
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(canonical["signal_id"], "signal-1")
        self.assertEqual(canonical["watch_items"], ["BTC 64k"])
        self.assertEqual(canonical["factor_count"], 1)

    def test_same_run_is_idempotent(self):
        store = self.store()
        first = store.record_completed_signal(run_record(), signal_record(), factors())
        second = store.record_completed_signal(run_record(), signal_record("ignored"), factors())
        self.assertEqual(first["status"], "recorded")
        self.assertEqual(second, {
            "status": "exists",
            "run_id": "run-1",
            "signal_id": "signal-1",
        })

    def test_one_run_can_hold_multiple_assets(self):
        store = self.store()
        store.record_completed_signal(run_record(), signal_record(), factors())
        eth_signal = signal_record("signal-eth")
        eth_signal["asset"] = "ETH"
        eth_signal["reference_price"] = 3200
        result = store.record_completed_signal(run_record(), eth_signal, factors())
        with closing(sqlite3.connect(self.db_path)) as connection:
            run_count = connection.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
            assets = connection.execute(
                "SELECT asset FROM daily_signals ORDER BY asset"
            ).fetchall()
        self.assertEqual(result["status"], "recorded")
        self.assertEqual(run_count, 1)
        self.assertEqual(assets, [("BTC",), ("ETH",)])

    def test_forced_rerun_preserves_old_signal_and_moves_canonical(self):
        store = self.store()
        store.record_completed_signal(run_record(), signal_record(), factors())
        store.record_completed_signal(
            run_record("run-2", "forced"), signal_record("signal-2"), factors()
        )
        canonical = store.get_canonical_signal("2026-07-12")
        with closing(sqlite3.connect(self.db_path)) as connection:
            rows = connection.execute(
                "SELECT signal_id, is_canonical FROM daily_signals ORDER BY signal_id"
            ).fetchall()
        self.assertEqual(rows, [("signal-1", 0), ("signal-2", 1)])
        self.assertEqual(canonical["signal_id"], "signal-2")

    def test_validation_failure_does_not_create_database(self):
        store = self.store()
        broken = signal_record()
        broken["confidence_raw"] = 101
        with self.assertRaises(SignalAuditValidationError):
            store.record_completed_signal(run_record(), broken, factors())
        self.assertFalse(self.db_path.exists())

    def test_naive_timestamp_is_rejected_before_database_creation(self):
        store = self.store()
        broken_run = run_record()
        broken_run["started_at"] = "2026-07-12T08:00:00"
        with self.assertRaises(SignalAuditValidationError):
            store.record_completed_signal(broken_run, signal_record(), factors())
        self.assertFalse(self.db_path.exists())

    def test_database_failure_rolls_back_run_and_canonical_change(self):
        store = self.store()
        store.record_completed_signal(run_record(), signal_record(), factors())
        with mock.patch.object(store, "_json", return_value="not-json"):
            with self.assertRaises(SignalAuditError):
                store.record_completed_signal(
                    run_record("run-2", "forced"),
                    signal_record("signal-2"),
                    factors(),
                )
        with closing(sqlite3.connect(self.db_path)) as connection:
            runs = connection.execute("SELECT run_id FROM audit_runs ORDER BY run_id").fetchall()
            signals = connection.execute(
                "SELECT signal_id, is_canonical FROM daily_signals ORDER BY signal_id"
            ).fetchall()
        self.assertEqual(runs, [("run-1",)])
        self.assertEqual(signals, [("signal-1", 1)])

    def test_second_connection_failure_is_wrapped_for_pipeline_isolation(self):
        store = self.store()
        real_connect = store._connect
        calls = 0

        def fail_second_connection():
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_connect()
            raise sqlite3.OperationalError("second connection unavailable")

        with mock.patch.object(store, "_connect", side_effect=fail_second_connection):
            with self.assertRaisesRegex(SignalAuditError, "failed to record"):
                store.record_completed_signal(run_record(), signal_record(), factors())

        with closing(sqlite3.connect(self.db_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0]
        self.assertEqual(count, 0)

    def test_data_quality_score_is_deterministic(self):
        score, flags = calculate_data_quality(
            {
                "crypto": {"BTC_Price": "暂无数据", "Fear_Greed": "暂无数据"},
                "macro": {"S&P500_Chg%": "暂无数据", "VIX_Volatility": 16},
            },
            [],
            version_known=False,
            reconciled=True,
        )
        self.assertEqual(score, 20)
        self.assertEqual(
            flags,
            [
                "missing_reference_price",
                "missing_sp500",
                "missing_fear_greed",
                "no_model_factors",
                "unknown_code_or_model_version",
                "reconciled_record",
            ],
        )


if __name__ == "__main__":
    unittest.main()
