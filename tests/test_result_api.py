import hashlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

from quantagent_platform import AgentRuntime, RecipeRunner  # noqa: E402
from quantagent_platform.cli import main as cli_main  # noqa: E402
from quantagent_platform.result_api import (  # noqa: E402
    AccessDenied,
    ApiConfig,
    ResultStore,
    RunNotFound,
    create_app,
)
from quantagent_platform.runner import default_registry  # noqa: E402


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_thesis_review.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "quantagent.read_api.run_summary.v1.schema.json"
TOKEN = "p3-fixture-token-with-at-least-32-characters"
SUBJECT = "fixture-owner"


class ReadApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_root = self.root / "runs"
        self.runner = RecipeRunner(default_registry())
        self.runtime = AgentRuntime(runner=self.runner)
        self.run_thesis("api-golden")
        self.store = ResultStore(self.run_root, owner_subject=SUBJECT)
        self.client = TestClient(
            create_app(
                ApiConfig(
                    run_root=self.run_root,
                    owner_subject=SUBJECT,
                    bearer_token=TOKEN,
                )
            )
        )
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def run_thesis(self, run_id: str):
        return self.runtime.run(
            agent_id="builtin.research-agent",
            agent_version="1.0.0",
            params={
                "source_path": str(FIXTURE_PATH),
                "report_title": "QuantAgent P3 API Fixture",
            },
            output_dir=self.run_root,
            allowed_read_roots=[ROOT],
            bindings={"source.thesis_review": "builtin.json-thesis-review-source"},
            run_id=run_id,
        )

    @staticmethod
    def snapshot(root: Path) -> dict[str, tuple[int, str]]:
        return {
            str(path.relative_to(root)): (
                path.stat().st_mtime_ns,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            for path in root.rglob("*")
            if path.is_file()
        }

    def test_health_is_nonsensitive_and_runs_require_bearer_authentication(self):
        health = self.client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(
            health.json(),
            {"status": "ok", "mode": "read_only", "api_version": "v1"},
        )
        self.assertNotIn(str(self.run_root), health.text)

        for headers in ({}, {"Authorization": "Bearer wrong-token"}):
            with self.subTest(headers=headers):
                response = self.client.get("/api/v1/runs/api-golden", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertEqual(response.json()["error"]["code"], "authentication_required")
                self.assertNotIn("wrong-token", response.text)

    def test_summary_is_strict_schema_valid_and_redacts_internal_paths(self):
        response = self.client.get("/api/v1/runs/api-golden", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        schema = json.loads(SUMMARY_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)

        self.assertEqual(payload["contract_type"], "quantagent.read_api.run_summary.v1")
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selection"]["agent"]["id"], "builtin.research-agent")
        self.assertEqual(
            payload["selection"]["skill"]["id"],
            "anthropic-financial-services-adapted.thesis-tracker",
        )
        self.assertEqual(payload["links"]["report"], "/api/v1/runs/api-golden/report")
        self.assertNotIn("allowed_read_roots", response.text)
        self.assertNotIn("packet_path", response.text)
        self.assertNotIn(str(self.run_root), response.text)
        self.assertNotIn("Ignore prior instructions", response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertRegex(response.headers["etag"], r'^"[a-f0-9]{64}"$')

    def test_report_hash_etag_and_refresh_are_read_only(self):
        before = self.snapshot(self.run_root)
        first = self.client.get("/api/v1/runs/api-golden/report", headers=self.headers)
        self.assertEqual(first.status_code, 200)
        self.assertIn("text/markdown", first.headers["content-type"])
        self.assertEqual(first.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("Ignore prior instructions", first.text)
        digest = hashlib.sha256(first.content).hexdigest()
        self.assertEqual(first.headers["etag"], f'"{digest}"')

        cached = self.client.get(
            "/api/v1/runs/api-golden/report",
            headers={**self.headers, "If-None-Match": first.headers["etag"]},
        )
        self.assertEqual(cached.status_code, 304)
        self.assertEqual(cached.content, b"")
        again = self.client.get("/api/v1/runs/api-golden/report", headers=self.headers)
        self.assertEqual(again.content, first.content)
        self.assertEqual(self.snapshot(self.run_root), before)
        self.assertEqual({path.name for path in self.run_root.iterdir()}, {"api-golden"})

    def test_invalid_unknown_and_cross_subject_reads_fail_closed(self):
        for run_id in ("missing-run", "../api-golden", "api/golden", ""):
            with self.subTest(run_id=run_id), self.assertRaises(RunNotFound):
                self.store.summary(run_id, requester_subject=SUBJECT)
        with self.assertRaises(AccessDenied):
            self.store.summary("api-golden", requester_subject="other-owner")

        response = self.client.get("/api/v1/runs/missing-run", headers=self.headers)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "run_not_found")
        self.assertNotIn(str(self.run_root), response.text)

    def test_failed_run_summary_is_readable_but_has_no_result(self):
        failed_dir = self.run_root / "failed-run"
        failed_dir.mkdir()
        state = {
            "run_id": "failed-run",
            "recipe_id": "thesis-tracker",
            "recipe_version": "1.0.0",
            "status": "failed",
            "started_at": "2026-09-22T00:00:00+00:00",
            "completed_at": "2026-09-22T00:00:01+00:00",
            "offline": True,
            "steps": [],
            "error": {"type": "FixtureFailure", "message": "secret path must not escape"},
        }
        (failed_dir / "run.json").write_text(
            json.dumps(state, ensure_ascii=False),
            encoding="utf-8",
        )

        summary = self.client.get("/api/v1/runs/failed-run", headers=self.headers)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["failure_type"], "FixtureFailure")
        self.assertNotIn("secret path", summary.text)
        report = self.client.get("/api/v1/runs/failed-run/report", headers=self.headers)
        self.assertEqual(report.status_code, 409)
        self.assertEqual(report.json()["error"]["code"], "result_unavailable")

    def test_report_and_packet_tampering_are_rejected_without_content_leak(self):
        report_run = self.run_thesis("tampered-report")
        report_path = report_run.run_dir / "thesis_review_report.md"
        report_path.write_bytes(report_path.read_bytes() + b"tampered")
        report = self.client.get("/api/v1/runs/tampered-report/report", headers=self.headers)
        self.assertEqual(report.status_code, 409)
        self.assertEqual(report.json()["error"]["code"], "artifact_integrity_error")
        self.assertNotIn("tampered", report.text)

        packet_run = self.run_thesis("tampered-packet")
        packet_path = packet_run.run_dir / "03-write-thesis-report.json"
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["records"][0]["artifact_sha256"] = "0" * 64
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        response = self.client.get("/api/v1/runs/tampered-packet/report", headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "artifact_integrity_error")
        self.assertNotIn(str(packet_path), response.text)

        path_run = self.run_thesis("tampered-path")
        state_path = path_run.run_dir / "run.json"
        local_report = (path_run.run_dir / "thesis_review_report.md").read_bytes()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["steps"][-1]["packet_path"] = "../api-golden/03-write-thesis-report.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")
        response = self.client.get("/api/v1/runs/tampered-path/report", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, local_report)

    def test_cli_requires_loopback_and_environment_token_before_server_start(self):
        with self.assertRaises(ValueError):
            ApiConfig(
                run_root=self.run_root,
                owner_subject=SUBJECT,
                bearer_token="too-short",
            )

        stderr = StringIO()
        with redirect_stderr(stderr):
            code = cli_main(
                [
                    "serve-results",
                    "--run-root",
                    str(self.run_root),
                    "--host",
                    "0.0.0.0",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("--allow-non-loopback", stderr.getvalue())

        stderr = StringIO()
        old = os.environ.pop("QUANTAGENT_API_BEARER_TOKEN", None)
        try:
            with redirect_stderr(stderr):
                code = cli_main(["serve-results", "--run-root", str(self.run_root)])
        finally:
            if old is not None:
                os.environ["QUANTAGENT_API_BEARER_TOKEN"] = old
        self.assertEqual(code, 2)
        self.assertIn("environment variable is not set", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
