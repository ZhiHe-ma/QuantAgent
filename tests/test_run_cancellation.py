import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quantagent_platform import AgentRuntime, RecipeError, RecipeRunner, RunCancelled  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample_thesis_review.json"
RECIPE = ROOT / "recipes" / "thesis_tracker.json"
BINDINGS = {"source.thesis_review": "builtin.json-thesis-review-source"}


class RunCancellationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output = Path(self.temp_dir.name) / "runs"
        self.recipe = RecipeRunner.load_recipe(RECIPE)
        self.runner = RecipeRunner()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_recipe(self, run_id, cancel_check):
        return self.runner.run(
            self.recipe,
            params={"source_path": str(FIXTURE), "report_title": "Cancellation test"},
            output_dir=self.output,
            allowed_read_roots=[ROOT],
            bindings=BINDINGS,
            run_id=run_id,
            cancel_check=cancel_check,
        )

    def state(self, run_id):
        return json.loads((self.output / run_id / "run.json").read_text(encoding="utf-8"))

    def test_cancel_before_first_step_records_terminal_state_without_plugins(self):
        with self.assertRaisesRegex(RunCancelled, "before step"):
            self.run_recipe("cancel-before-first", lambda: True)
        state = self.state("cancel-before-first")
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["error"]["type"], "RunCancelled")
        self.assertIn("completed_at", state)
        self.assertEqual(state["steps"], [])
        self.assertEqual(
            {path.name for path in (self.output / "cancel-before-first").iterdir()},
            {"run.json"},
        )
        with self.assertRaises(FileExistsError):
            self.run_recipe("cancel-before-first", lambda: False)
        self.assertEqual(self.state("cancel-before-first"), state)

    def test_cancel_between_steps_preserves_completed_provenance_and_skips_later_steps(self):
        checks = 0

        def cancel_after_source():
            nonlocal checks
            checks += 1
            return checks == 2

        with self.assertRaises(RunCancelled):
            self.run_recipe("cancel-after-source", cancel_after_source)
        state = self.state("cancel-after-source")
        self.assertEqual(checks, 2)
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual([step["id"] for step in state["steps"]], ["load-thesis-review"])
        self.assertTrue((self.output / "cancel-after-source" / "01-load-thesis-review.json").is_file())
        self.assertFalse((self.output / "cancel-after-source" / "thesis_review_report.md").exists())

    def test_agent_runtime_forwards_cancellation_to_same_runner(self):
        runtime = AgentRuntime(runner=self.runner)
        with self.assertRaises(RunCancelled):
            runtime.run(
                agent_id="builtin.research-agent",
                agent_version="1.0.0",
                params={"source_path": str(FIXTURE), "report_title": "Cancellation test"},
                output_dir=self.output,
                allowed_read_roots=[ROOT],
                bindings=BINDINGS,
                run_id="agent-cancelled",
                cancel_check=lambda: True,
            )
        state = self.state("agent-cancelled")
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["invocation"]["agent"]["id"], "builtin.research-agent")

    def test_invalid_or_broken_callback_is_not_misreported_as_cancellation(self):
        with self.assertRaisesRegex(RecipeError, "cancel_check must be callable"):
            self.run_recipe("invalid-callback", True)
        self.assertFalse((self.output / "invalid-callback").exists())

        def broken_callback():
            raise RuntimeError("callback failed")

        with self.assertRaisesRegex(RecipeError, "callback failed"):
            self.run_recipe("broken-callback", broken_callback)
        state = self.state("broken-callback")
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error"]["type"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
