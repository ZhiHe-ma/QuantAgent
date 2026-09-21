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
from quantagent_platform.qlib_plugins import FACTOR_RESEARCH_CONTRACT  # noqa: E402


RECIPE_PATH = ROOT / "recipes" / "qlib_factor_research.json"
DATA_FIXTURE = ROOT / "tests" / "fixtures" / "sample_qlib_factor.csv"
FAKE_WORKER = ROOT / "tests" / "fixtures" / "fake_qlib_worker.py"


class QlibPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "runs"
        self.data_path = self.root / "factor.csv"
        shutil.copyfile(DATA_FIXTURE, self.data_path)
        self.recipe = RecipeRunner.load_recipe(RECIPE_PATH)

    def tearDown(self):
        self.temp_dir.cleanup()

    def options(self, worker_path=FAKE_WORKER):
        return {
            "python_executable": sys.executable,
            "worker_path": str(worker_path),
            "timeout_seconds": 30,
            "min_rows_per_date": 3,
        }

    def run_recipe(self, run_id, options=None):
        return RecipeRunner().run(
            self.recipe,
            params={"source_path": str(self.data_path), "qlib_options": options or self.options()},
            output_dir=self.output,
            allowed_read_roots=[self.root, ROOT, Path(sys.executable).resolve().parent],
            allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"},
            run_id=run_id,
        )

    def test_protocol_worker_runs_in_subprocess_and_report_states_limits(self):
        secret = "must-not-reach-worker-or-artifacts"
        with mock.patch.dict(os.environ, {"QUANTAGENT_TEST_SECRET": secret}, clear=False):
            result = self.run_recipe("protocol-test")
        self.assertEqual(result.status, "completed")
        packet = json.loads(
            (result.run_dir / "01-run-qlib-factor-research.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["contract_version"], FACTOR_RESEARCH_CONTRACT)
        self.assertTrue(packet["metadata"]["isolated_process"])
        self.assertEqual(packet["metadata"]["runtime"]["pyqlib"], "not-exercised")
        report = (result.run_dir / "qlib_factor_research.md").read_text(encoding="utf-8")
        self.assertIn("实验性适配器", report)
        self.assertIn("不代表收益、可交易性", report)
        self.assertIn("未执行模型训练", report)
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
                params={"source_path": str(self.data_path), "qlib_options": self.options()},
                output_dir=self.output,
                allowed_read_roots=[self.root, ROOT, Path(sys.executable).resolve().parent],
                run_id="permission-denied",
            )
        self.assertFalse((self.output / "permission-denied").exists())

    def test_python_executable_must_be_inside_allowed_read_roots(self):
        with self.assertRaisesRegex(RecipeError, "outside allowed roots"):
            RecipeRunner().run(
                self.recipe,
                params={"source_path": str(self.data_path), "qlib_options": self.options()},
                output_dir=self.output,
                allowed_read_roots=[self.root, ROOT],
                allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"},
                run_id="python-denied",
            )

    def test_worker_error_fails_closed_and_records_failed_state(self):
        broken_worker = self.root / "broken_worker.py"
        broken_worker.write_text("raise RuntimeError('intentional worker failure')\n", encoding="utf-8")
        with self.assertRaisesRegex(RecipeError, "produced no response"):
            self.run_recipe("worker-failed", self.options(broken_worker))
        state = json.loads((self.output / "worker-failed" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "failed")

    @unittest.skipUnless(os.environ.get("QUANTAGENT_QLIB_PYTHON"), "set QUANTAGENT_QLIB_PYTHON for real Qlib test")
    def test_real_pyqlib_static_loader(self):
        qlib_python = Path(os.environ["QUANTAGENT_QLIB_PYTHON"]).resolve()
        options = self.options(ROOT / "quantagent_platform" / "qlib_worker.py")
        options["python_executable"] = str(qlib_python)
        result = RecipeRunner().run(
            self.recipe,
            params={"source_path": str(self.data_path), "qlib_options": options},
            output_dir=self.output,
            allowed_read_roots=[self.root, ROOT, qlib_python.parent],
            allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"},
            run_id="real-qlib",
        )
        packet = json.loads(
            (result.run_dir / "01-run-qlib-factor-research.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["metadata"]["runtime"]["pyqlib"], "0.9.7")
        self.assertEqual(packet["metadata"]["loader"], "qlib.data.dataset.loader.StaticDataLoader")
        self.assertEqual(packet["records"][0]["row_count"], 20)
        self.assertEqual(packet["records"][0]["valid_rank_ic_date_count"], 4)


if __name__ == "__main__":
    unittest.main()
