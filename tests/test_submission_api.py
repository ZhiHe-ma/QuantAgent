import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from jsonschema import Draft202012Validator  # noqa: E402

from quantagent_platform.cli import main as cli_main  # noqa: E402
from quantagent_platform.result_api import ApiConfig, create_app  # noqa: E402
from quantagent_platform.submission_api import SubmissionConfig, _run_id  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample_thesis_review.json"
TOKEN = "p3-submit-fixture-token-with-at-least-32-characters"
SUBJECT = "local-owner"


class SubmissionApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_root = self.root / "runs"
        self.run_root.mkdir()
        self.fixture_path = self.root / "review.json"
        shutil.copyfile(FIXTURE, self.fixture_path)
        self.sha256 = hashlib.sha256(self.fixture_path.read_bytes()).hexdigest()
        self.body = {
            "contract_type": "quantagent.submit_run.v1",
            "fixture_id": "thesis",
            "fixture_sha256": self.sha256,
            "request_id": "request.btc.thesis.20260922",
        }
        self.headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": "unique-fixture-request-001",
        }
        self.client = TestClient(
            create_app(
                ApiConfig(run_root=self.run_root, owner_subject=SUBJECT, bearer_token=TOKEN),
                submission=SubmissionConfig({"thesis": self.fixture_path, "other": self.fixture_path}),
            )
        )

    def tearDown(self):
        self.client.close()
        self.temp_dir.cleanup()

    def test_opt_in_submission_executes_once_and_is_readable(self):
        schema = json.loads(
            (ROOT / "schemas" / "quantagent.submit_run.v1.schema.json").read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(self.body)
        self.assertEqual(self.client.get("/healthz").json()["mode"], "controlled_local_submit")
        first = self.client.post("/api/v1/runs", json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.headers["cache-control"], "private, no-store")
        run_id = first.json()["run_id"]
        self.assertEqual(first.headers["location"], f"/api/v1/runs/{run_id}")
        self.assertEqual(first.json()["status"], "completed")
        self.assertEqual(first.json()["selection"]["agent"]["id"], "builtin.research-agent")
        self.assertNotIn(str(self.fixture_path), first.text)
        self.assertNotIn(TOKEN, first.text)

        state = json.loads((self.run_root / run_id / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(state["invocation"]["submission"]["fixture_sha256"], self.sha256)
        self.assertEqual(state["allowed_permissions"], ["filesystem:read", "filesystem:write"])
        self.assertTrue(state["offline"])
        report = self.client.get(f"/api/v1/runs/{run_id}/report", headers=self.headers)
        self.assertEqual(report.status_code, 200)
        self.assertIn("text/markdown", report.headers["content-type"])

        before = sorted(self.run_root.iterdir())
        repeated = self.client.post("/api/v1/runs", json=self.body, headers=self.headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json(), first.json())
        self.assertEqual(sorted(self.run_root.iterdir()), before)
        self.assertEqual(self.client.get(f"/api/v1/runs/{run_id}", headers=self.headers).status_code, 200)

    def test_read_only_app_still_has_no_submission_route(self):
        with TestClient(create_app(ApiConfig(self.run_root, SUBJECT, TOKEN))) as client:
            self.assertEqual(client.get("/healthz").json()["mode"], "read_only")
            self.assertEqual(client.post("/api/v1/runs", json=self.body, headers=self.headers).status_code, 404)

    def test_authentication_and_idempotency_conflict_fail_closed(self):
        missing_auth = self.client.post("/api/v1/runs", json=self.body)
        self.assertEqual(missing_auth.status_code, 401)
        self.assertEqual(list(self.run_root.iterdir()), [])

        first = self.client.post("/api/v1/runs", json=self.body, headers=self.headers)
        self.assertEqual(first.status_code, 201)
        changed = {**self.body, "fixture_id": "other"}
        conflict = self.client.post("/api/v1/runs", json=changed, headers=self.headers)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["error"]["code"], "idempotency_conflict")
        self.assertEqual(len(list(self.run_root.iterdir())), 1)

    def test_invalid_requests_never_create_a_run(self):
        cases = [
            ({**self.body, "fixture_id": "unknown"}, self.headers),
            ({**self.body, "fixture_sha256": "0" * 64}, self.headers),
            ({**self.body, "request_id": "wrong-request"}, self.headers),
            ({**self.body, "source_path": "C:/secret/file.json"}, self.headers),
            (self.body, {"Authorization": f"Bearer {TOKEN}"}),
            (self.body, {**self.headers, "Idempotency-Key": "short"}),
        ]
        for body, headers in cases:
            with self.subTest(body=body, headers=headers):
                response = self.client.post("/api/v1/runs", json=body, headers=headers)
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(list(self.run_root.iterdir()), [])

        duplicate_key = json.dumps(self.body).replace('"fixture_id": "thesis",', '"fixture_id": "thesis", "fixture_id": "other",')
        duplicate = self.client.post(
            "/api/v1/runs",
            content=duplicate_key,
            headers={**self.headers, "Content-Type": "application/json"},
        )
        self.assertEqual(duplicate.status_code, 422)
        oversized = self.client.post(
            "/api/v1/runs",
            content=b" " * 4097,
            headers={**self.headers, "Content-Type": "application/json"},
        )
        self.assertEqual(oversized.status_code, 413)
        self.assertEqual(list(self.run_root.iterdir()), [])

    def test_changed_registered_fixture_and_existing_reservation_are_not_run(self):
        self.fixture_path.write_bytes(self.fixture_path.read_bytes() + b"\n")
        changed = self.client.post("/api/v1/runs", json=self.body, headers=self.headers)
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "fixture_changed")
        self.assertEqual(list(self.run_root.iterdir()), [])

        run_id = _run_id(SUBJECT, self.headers["Idempotency-Key"])
        (self.run_root / run_id).mkdir()
        pending = self.client.post("/api/v1/runs", json=self.body, headers=self.headers)
        self.assertEqual(pending.status_code, 409)
        self.assertEqual(pending.json()["error"]["code"], "submission_pending")

    def test_registered_input_cannot_be_inside_run_root(self):
        internal_fixture = self.run_root / "review.json"
        shutil.copyfile(FIXTURE, internal_fixture)
        with self.assertRaisesRegex(ValueError, "outside the run root"):
            create_app(
                ApiConfig(self.run_root, SUBJECT, TOKEN),
                submission=SubmissionConfig({"internal": internal_fixture}),
            )
        self.assertEqual(sorted(self.run_root.iterdir()), [internal_fixture])

    def test_symlink_run_root_is_rejected_before_submission(self):
        target = self.root / "other-runs"
        target.mkdir()
        linked_root = self.root / "linked-runs"
        try:
            linked_root.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windows symlink creation requires Developer Mode or privilege")
            raise
        try:
            for submission in (None, SubmissionConfig({"thesis": self.fixture_path})):
                with self.subTest(submission=submission is not None):
                    with self.assertRaisesRegex(ValueError, "run_root must be an existing non-link"):
                        create_app(ApiConfig(linked_root, SUBJECT, TOKEN), submission=submission)
            self.assertEqual(list(target.iterdir()), [])
        finally:
            linked_root.unlink()

    @unittest.skipUnless(os.name == "nt", "junctions are Windows-only")
    def test_junction_run_root_is_rejected_before_submission(self):
        target = self.root / "other-runs"
        target.mkdir()
        linked_root = self.root / "linked-runs"
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(linked_root), str(target)],
            check=True,
            capture_output=True,
            text=True,
        )
        try:
            self.assertTrue(linked_root.is_junction())
            with self.assertRaisesRegex(ValueError, "run_root must be an existing non-link"):
                create_app(
                    ApiConfig(linked_root, SUBJECT, TOKEN),
                    submission=SubmissionConfig({"thesis": self.fixture_path}),
                )
            with patch.dict(os.environ, {"QUANTAGENT_API_BEARER_TOKEN": TOKEN}):
                with patch("uvicorn.run") as serve, redirect_stderr(StringIO()) as stderr:
                    code = cli_main([
                        "serve-research", "--run-root", str(linked_root),
                        "--fixture", f"thesis={self.fixture_path}",
                    ])
            self.assertEqual(code, 2)
            self.assertIn("run_root must be an existing non-link", stderr.getvalue())
            serve.assert_not_called()
            self.assertEqual(list(target.iterdir()), [])
        finally:
            linked_root.rmdir()

    def test_concurrent_same_key_executes_at_most_once(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(
                pool.map(
                    lambda _: self.client.post("/api/v1/runs", json=self.body, headers=self.headers),
                    range(4),
                )
            )
        self.assertEqual(sorted(response.status_code for response in responses), [200, 200, 200, 201])
        self.assertEqual(len({response.json()["run_id"] for response in responses}), 1)
        self.assertEqual(len(list(self.run_root.iterdir())), 1)

    def test_cli_requires_literal_loopback_and_registered_input(self):
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = cli_main([
                "serve-research", "--run-root", str(self.run_root),
                "--fixture", f"thesis={self.fixture_path}", "--host", "localhost",
            ])
        self.assertEqual(code, 2)
        self.assertIn("literal loopback", stderr.getvalue())

        stderr = StringIO()
        previous = os.environ.pop("QUANTAGENT_API_BEARER_TOKEN", None)
        try:
            with redirect_stderr(stderr):
                code = cli_main([
                    "serve-research", "--run-root", str(self.run_root),
                    "--fixture", f"thesis={self.fixture_path}",
                ])
        finally:
            if previous is not None:
                os.environ["QUANTAGENT_API_BEARER_TOKEN"] = previous
        self.assertEqual(code, 2)
        self.assertIn("environment variable is not set", stderr.getvalue())

    def test_cli_opt_in_starts_submission_app_without_running_at_startup(self):
        with patch.dict(os.environ, {"QUANTAGENT_API_BEARER_TOKEN": TOKEN}):
            with patch("uvicorn.run") as serve:
                code = cli_main([
                    "serve-research", "--run-root", str(self.run_root),
                    "--fixture", f"thesis={self.fixture_path}",
                ])
        self.assertEqual(code, 0)
        self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")
        self.assertEqual(list(self.run_root.iterdir()), [])
        with TestClient(serve.call_args.args[0]) as client:
            self.assertEqual(client.get("/healthz").json()["mode"], "controlled_local_submit")


if __name__ == "__main__":
    unittest.main()
