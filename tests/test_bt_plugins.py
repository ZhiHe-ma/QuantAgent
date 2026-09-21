import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import RecipeError, RecipeRunner  # noqa: E402
from quantagent_platform.bt_plugins import BACKTEST_RESULT_CONTRACT  # noqa: E402
from quantagent_platform.bt_worker import _require_aware_timestamp, lagged_equal_weights  # noqa: E402


RECIPE_PATH = ROOT / "recipes" / "bt_portfolio_backtest.json"
DATA_FIXTURE = ROOT / "tests" / "fixtures" / "sample_bt_panel.csv"
FAKE_WORKER = ROOT / "tests" / "fixtures" / "fake_bt_worker.py"


class BtPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.data_path = self.root / "panel.csv"
        shutil.copyfile(DATA_FIXTURE, self.data_path)
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)

    def tearDown(self):
        self.temp_dir.cleanup()

    def options(self, worker_path=FAKE_WORKER):
        return {
            "python_executable": sys.executable,
            "worker_path": str(worker_path),
            "price_semantics": "synthetic_close",
            "execution_lag_bars": 1,
            "top_n": 1,
            "commission_bps": 5,
            "slippage_bps": 5,
            "periods_per_year": 365,
            "timeout_seconds": 30,
        }

    def run_recipe(self, run_id, options=None):
        return RecipeRunner().run(
            self.recipe,
            params={"source_path": str(self.data_path), "backtest_options": options or self.options()},
            output_dir=self.output,
            allowed_read_roots=[self.root, ROOT, Path(sys.executable).resolve().parent],
            allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"},
            run_id=run_id,
        )

    def test_lagged_weights_never_use_same_bar_signal(self):
        weights = lagged_equal_weights(
            ["A", "B"],
            [[0.9, 0.1], [0.2, 0.8], [0.7, 0.3]],
            execution_lag_bars=1,
            top_n=1,
            min_signal=0.0,
        )
        self.assertEqual(weights[0], [0.0, 0.0])
        self.assertEqual(weights[1], [1.0, 0.0])
        self.assertEqual(weights[2], [0.0, 1.0])
        with self.assertRaisesRegex(ValueError, "at least 1"):
            lagged_equal_weights(
                ["A"], [[1.0]], execution_lag_bars=0, top_n=1, min_signal=0.0
            )

    def test_timestamps_require_explicit_timezone(self):
        _require_aware_timestamp("2026-01-01T00:00:00Z")
        with self.assertRaisesRegex(ValueError, "timezone"):
            _require_aware_timestamp("2026-01-01T00:00:00")

    def test_protocol_worker_and_report_preserve_assumptions_without_secret(self):
        secret = "must-not-reach-worker-or-artifacts"
        with mock.patch.dict(os.environ, {"QUANTAGENT_TEST_SECRET": secret}, clear=False):
            result = self.run_recipe("protocol-test")
        packet = json.loads(
            (result.run_dir / "01-run-bt-portfolio-backtest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["contract_version"], BACKTEST_RESULT_CONTRACT)
        self.assertTrue(packet["metadata"]["isolated_process"])
        self.assertEqual(packet["metadata"]["runtime"]["bt"], "not-exercised")
        report = (result.run_dir / "bt_portfolio_backtest.md").read_text(encoding="utf-8")
        self.assertIn("信号延迟：1 根 bar", report)
        self.assertIn("等权买入持有", report)
        self.assertIn("不代表未来收益", report)
        persisted = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in result.run_dir.iterdir()
            if path.is_file()
        )
        self.assertNotIn(secret, persisted)

    def test_process_permission_is_required_before_run_directory_creation(self):
        with self.assertRaisesRegex(RecipeError, "process:spawn"):
            RecipeRunner().run(
                self.recipe,
                params={"source_path": str(self.data_path), "backtest_options": self.options()},
                output_dir=self.output,
                allowed_read_roots=[self.root, ROOT, Path(sys.executable).resolve().parent],
                run_id="permission-denied",
            )
        self.assertFalse((self.output / "permission-denied").exists())

    def test_price_semantics_is_required(self):
        options = self.options()
        del options["price_semantics"]
        with self.assertRaisesRegex(RecipeError, "price_semantics"):
            self.run_recipe("missing-semantics", options)

    def test_worker_error_fails_closed(self):
        broken_worker = self.root / "broken_worker.py"
        broken_worker.write_text("raise RuntimeError('intentional worker failure')\n", encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "produced no response"):
            self.run_recipe("worker-failed", self.options(broken_worker))
        state = json.loads((self.output / "worker-failed" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    def test_worker_cannot_silently_change_execution_assumptions(self):
        mismatched_worker = self.root / "mismatched_worker.py"
        source = FAKE_WORKER.read_text(encoding="utf-8").replace(
            '"long_only": True', '"long_only": False'
        )
        mismatched_worker.write_text(source, encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "long_only does not match"):
            self.run_recipe("worker-mismatch", self.options(mismatched_worker))
        state = json.loads((self.output / "worker-mismatch" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    @unittest.skipUnless(os.environ.get("QUANTAGENT_BT_PYTHON"), "set QUANTAGENT_BT_PYTHON for real bt test")
    def test_real_bt_engine(self):
        bt_python = Path(os.environ["QUANTAGENT_BT_PYTHON"]).resolve()
        options = self.options(ROOT / "quantagent_platform" / "bt_worker.py")
        options["python_executable"] = str(bt_python)
        result = RecipeRunner().run(
            self.recipe,
            params={"source_path": str(self.data_path), "backtest_options": options},
            output_dir=self.output,
            allowed_read_roots=[self.root, ROOT, bt_python.parent],
            allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"},
            run_id="real-bt",
        )
        packet = json.loads(
            (result.run_dir / "01-run-bt-portfolio-backtest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["metadata"]["runtime"]["bt"], "1.2.3")
        self.assertEqual(packet["records"][0]["input_row_count"], 30)
        self.assertEqual(packet["records"][0]["parameters"]["execution_lag_bars"], 1)
        self.assertEqual(packet["records"][0]["equity_curve"][0]["strategy_equity"], 100000.0)


if __name__ == "__main__":
    unittest.main()
