"""P5 operator command and existing authenticated Result API readback."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from quantagent_platform.cli import main as cli_main
from quantagent_platform.contracts import canonical_json
from quantagent_platform.p5_registry import RAW_NAMES
from quantagent_platform.result_api import ApiConfig, create_app
from quantagent_platform.runner import RecipeRunner, default_registry
from tests.test_sec_contracts import make_responses


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "p5-test-token-with-at-least-thirty-two-characters"


class P5CliApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p4_root = self.root / "p4-runs"
        recipe = RecipeRunner.load_recipe(ROOT / "recipes" / "sec_industry_peers.json")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=make_responses()):
                p4 = RecipeRunner(default_registry()).run(
                    recipe, params={"source_path": "", "report_title": "Synthetic SEC sample"},
                    output_dir=self.p4_root, allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False, run_id="synthetic-p4-run",
                )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.registry_path = self.root / "approved.json"
        self.registry_path.write_text(canonical_json({
            "registry_version": "quantagent.sec_approved_run.v1",
            "entries": [{
                "approved_source_id": "synthetic-p4", "run_id": p4.run_id,
                "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
                "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
                "packet_sha256": digest(p4.run_dir / "01-load-sec-facts.json"),
                "report_sha256": digest(p4.run_dir / "sec_industry_peers.md"),
                "raw_sha256": {name: digest(p4.run_dir / name) for name in RAW_NAMES},
            }],
        }), encoding="utf-8")
        self.run_root = self.root / "p5-runs"

    def command(self, source_id: str = "synthetic-p4", request_id: str = "request-001"):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main([
                "review-sec-evidence",
                "--approved-registry", str(self.registry_path),
                "--approved-run-root", str(self.p4_root),
                "--run-root", str(self.run_root),
                "--source-id", source_id,
                "--request-id", request_id,
            ])
        return code, out.getvalue(), err.getvalue()

    @staticmethod
    def snapshot(root: Path) -> dict[str, tuple[int, str]]:
        return {
            str(path.relative_to(root)): (
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ) for path in root.rglob("*") if path.is_file()
        }

    def test_command_and_read_api_report_integrity(self) -> None:
        code, out, err = self.command()
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        child_id = result["child_run_id"]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["handoff_calls"], 1)
        self.assertTrue(child_id.startswith("p5c-"))
        self.assertEqual(out.count(child_id), 1)
        repeated = self.command()
        self.assertEqual(repeated[0], 0)
        self.assertEqual(json.loads(repeated[1]), result)

        client = TestClient(create_app(ApiConfig(
            run_root=self.run_root, owner_subject="fixture-owner", bearer_token=TOKEN)))
        self.addCleanup(client.close)
        headers = {"Authorization": f"Bearer {TOKEN}"}
        before = self.snapshot(self.run_root)
        self.assertEqual(client.get(f"/api/v1/runs/{child_id}").status_code, 401)
        summary = client.get(f"/api/v1/runs/{child_id}", headers=headers)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["selection"]["agent"]["id"],
                         "builtin.sec-evidence-review-agent")
        report = client.get(f"/api/v1/runs/{child_id}/report", headers=headers)
        self.assertEqual(report.status_code, 200)
        self.assertTrue(report.text.startswith("# Independent SEC evidence review"))
        self.assertEqual(report.headers["etag"],
                         f'"{hashlib.sha256(report.content).hexdigest()}"')
        self.assertEqual(before, self.snapshot(self.run_root))
        (self.run_root / child_id / "sec_independent_review.md").write_bytes(
            report.content + b"tampered")
        self.assertEqual(client.get(f"/api/v1/runs/{child_id}/report",
                                    headers=headers).status_code, 409)

    def test_unknown_source_and_extra_target_are_rejected(self) -> None:
        code, out, err = self.command(source_id="not-approved")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertFalse(self.run_root.exists() and any(
            child.name.startswith("p5p-") for child in self.run_root.iterdir()))
        with self.assertRaises(SystemExit) as caught:
            cli_main([
                "review-sec-evidence", "--approved-registry", str(self.registry_path),
                "--approved-run-root", str(self.p4_root), "--run-root", str(self.run_root),
                "--source-id", "synthetic-p4", "--request-id", "request-extra",
                "--target-agent", "builtin.unapproved-agent",
            ])
        self.assertEqual(caught.exception.code, 2)

    def test_worker_failure_returns_one_without_private_error_text(self) -> None:
        raw_path = self.p4_root / "synthetic-p4-run" / RAW_NAMES[0]
        raw_path.write_bytes(raw_path.read_bytes() + b"tampered")
        code, out, err = self.command(request_id="request-tampered")
        self.assertEqual(code, 1)
        result = json.loads(out)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_code"], "parent_failed")
        self.assertIsNone(result["child_run_id"])
        self.assertNotIn(str(self.p4_root), out + err)

    def test_generic_agent_and_recipe_commands_reject_p5_route(self) -> None:
        for agent_id in (
            "builtin.sec-evidence-producer-agent",
            "builtin.sec-evidence-review-agent",
        ):
            with self.subTest(agent_id=agent_id):
                out, err = StringIO(), StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    code = cli_main([
                        "run-agent", agent_id, "--agent-version", "1.0.0",
                        "--source", "json", "--input",
                        str(ROOT / "tests" / "fixtures" / "sample_signals.json"),
                        "--output-dir", str(self.root / "generic-runs"),
                    ])
                self.assertEqual(code, 2)
                self.assertIn("coordinator", err.getvalue().lower())
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main([
                "run", str(ROOT / "recipes" / "sec_evidence_producer.json"),
                "--source", "json", "--input",
                str(ROOT / "tests" / "fixtures" / "sample_signals.json"),
            ])
        self.assertEqual(code, 2)
        self.assertIn("coordinator", err.getvalue().lower())
        self.assertFalse((self.root / "generic-runs").exists())


if __name__ == "__main__":
    unittest.main()
