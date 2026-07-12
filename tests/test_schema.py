import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "sql" / "001_signal_audit.sql"


class SignalAuditSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "signal_audit.sqlite3"
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.sql = MIGRATION.read_text(encoding="utf-8")
        self.connection.executescript(self.sql)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def insert_run(self, run_id, run_kind="scheduled"):
        self.connection.execute(
            """
            INSERT INTO audit_runs (
                run_id, trade_date, started_at, completed_at, run_kind, status,
                code_version, source_sha256, fast_model, reason_model,
                report_written, wecom_sent, memory_saved
            ) VALUES (?, '2026-07-12', '2026-07-12T08:00:00+08:00',
                      '2026-07-12T08:01:00+08:00', ?, 'completed',
                      'v5.2', 'sha256', 'flash', 'pro', 1, 1, 1)
            """,
            (run_id, run_kind),
        )

    def insert_signal(self, signal_id, run_id, canonical=1, watch_items=None):
        self.connection.execute(
            """
            INSERT INTO daily_signals (
                signal_id, run_id, signal_date, asset, decision_horizon,
                risk_regime, bias, confidence_raw, core_thesis, invalid_if,
                today_check, watch_items_json, reference_price,
                market_snapshot_json, factors_json, previous_memory_json,
                analysis_text, factor_count, data_quality_score,
                quality_flags_json, is_canonical, finalized_at
            ) VALUES (?, ?, '2026-07-12', 'BTC', '1d', 'mixed',
                      'slightly_bullish', 70, 'thesis', 'invalid', 'check',
                      ?, 64000, ?, ?, ?, 'analysis', 1, 95, ?, ?,
                      '2026-07-12T08:01:00+08:00')
            """,
            (
                signal_id,
                run_id,
                json.dumps(["BTC"]) if watch_items is None else watch_items,
                json.dumps({"crypto": {"BTC_Price": 64000}}),
                json.dumps([{"title": "factor"}]),
                json.dumps({}),
                json.dumps([]),
                canonical,
            ),
        )

    def test_migration_is_idempotent(self):
        self.connection.executescript(self.sql)
        rows = self.connection.execute(
            "SELECT version, name FROM schema_migrations ORDER BY version"
        ).fetchall()
        self.assertEqual(rows, [(1, "initial_signal_audit")])

    def test_expected_tables_exist(self):
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue(
            {
                "schema_migrations",
                "audit_runs",
                "daily_signals",
                "signal_factors",
                "signal_outcomes",
            }.issubset(tables)
        )

    def test_forced_rerun_preserves_history_and_moves_canonical(self):
        self.insert_run("run-1")
        self.insert_signal("signal-1", "run-1")
        self.connection.commit()
        self.insert_run("run-2", "forced")

        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_signal("signal-2", "run-2")
        self.connection.rollback()

        # Recreate the second run because rollback also removed its uncommitted row.
        self.connection.execute(
            "UPDATE daily_signals SET is_canonical = 0 WHERE signal_id = 'signal-1'"
        )
        self.insert_run("run-2", "forced")
        self.insert_signal("signal-2", "run-2")
        self.connection.commit()

        rows = self.connection.execute(
            "SELECT signal_id, is_canonical FROM daily_signals ORDER BY signal_id"
        ).fetchall()
        self.assertEqual(rows, [("signal-1", 0), ("signal-2", 1)])

    def test_invalid_json_is_rejected(self):
        self.insert_run("run-json")
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert_signal("signal-json", "run-json", watch_items="not-json")

    def test_factor_and_outcome_rows_cascade_with_signal(self):
        self.insert_run("run-cascade")
        self.insert_signal("signal-cascade", "run-cascade")
        self.connection.execute(
            """
            INSERT INTO signal_factors (
                signal_id, ordinal, source, title, sentiment, weight, reason, raw_json
            ) VALUES ('signal-cascade', 0, 'rss', 'title', 'neutral', 'Medium',
                      'reason', '{}')
            """
        )
        self.connection.execute(
            """
            INSERT INTO signal_outcomes (
                signal_id, horizon_hours, observed_at, entry_price, exit_price,
                return_pct, price_source, data_quality_score, raw_json
            ) VALUES ('signal-cascade', 24, '2026-07-13T08:00:00+08:00',
                      64000, 65000, 1.5625, 'binance', 100, '{}')
            """
        )
        self.connection.execute(
            "DELETE FROM daily_signals WHERE signal_id = 'signal-cascade'"
        )
        factor_count = self.connection.execute(
            "SELECT COUNT(*) FROM signal_factors"
        ).fetchone()[0]
        outcome_count = self.connection.execute(
            "SELECT COUNT(*) FROM signal_outcomes"
        ).fetchone()[0]
        self.assertEqual((factor_count, outcome_count), (0, 0))


if __name__ == "__main__":
    unittest.main()
