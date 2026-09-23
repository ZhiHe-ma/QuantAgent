import hashlib
import json
import shutil
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from jsonschema import Draft202012Validator, FormatChecker  # noqa: E402

from quantagent_platform.agents import AgentRuntime  # noqa: E402
from quantagent_platform.result_api import ApiConfig, create_app  # noqa: E402
from quantagent_platform.runner import RunCancelled  # noqa: E402
from quantagent_platform.submission_api import SubmissionConfig  # noqa: E402
from quantagent_platform.task_lifecycle_api import _task_id  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample_thesis_review.json"
SCHEMA = ROOT / "schemas" / "quantagent.run_status.v2.schema.json"
TOKEN = "p3-v2-local-task-token-at-least-32-characters"
SUBJECT = "local-owner"


class TaskLifecycleApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_root = self.root / "runs"
        self.run_root.mkdir()
        self.fixture = self.root / "review.json"
        shutil.copyfile(FIXTURE, self.fixture)
        self.body = {
            "contract_type": "quantagent.submit_run.v1",
            "fixture_id": "thesis",
            "fixture_sha256": hashlib.sha256(self.fixture.read_bytes()).hexdigest(),
            "request_id": "request.btc.thesis.20260922",
        }
        self.headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Idempotency-Key": "task-lifecycle-key-0001",
        }
        self.app = create_app(
            ApiConfig(self.run_root, SUBJECT, TOKEN),
            submission=SubmissionConfig({"thesis": self.fixture, "alternate": self.fixture}),
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.state.local_task_worker.executor.shutdown(wait=True)
        self.client.close()
        self.temp_dir.cleanup()

    def wait_status(self, run_id, expected, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = self.client.get(f"/api/v2/runs/{run_id}", headers=self.headers)
            if response.status_code == 200 and response.json()["status"] == expected:
                return response
            time.sleep(0.01)
        self.fail(f"task {run_id} did not reach {expected}: {response.text}")

    def test_async_submit_status_schema_idempotency_and_completed_report(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        self.assertEqual(self.client.get("/healthz").json()["api_version"], "v2")
        submit = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        self.assertEqual(submit.status_code, 202, submit.text)
        run_id = submit.json()["run_id"]
        self.assertRegex(run_id, r"^task-[a-f0-9]{32}$")
        self.assertEqual(submit.headers["location"], f"/api/v2/runs/{run_id}")
        self.assertEqual(submit.headers["cache-control"], "private, no-store")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(submit.json())

        completed = self.wait_status(run_id, "completed")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(completed.json())
        self.assertEqual(completed.json()["links"]["summary"], f"/api/v1/runs/{run_id}")
        self.assertEqual(completed.json()["links"]["report"], f"/api/v1/runs/{run_id}/report")
        self.assertEqual(self.client.get(completed.json()["links"]["report"], headers=self.headers).status_code, 200)
        state = json.loads((self.run_root / run_id / "run.json").read_text(encoding="utf-8"))
        self.assertTrue(state["offline"])
        self.assertEqual(state["allowed_permissions"], ["filesystem:read", "filesystem:write"])
        self.assertEqual(state["invocation"]["submission"]["contract_type"], "quantagent.run_status.v2")
        repeated = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["run_id"], run_id)
        self.assertEqual(len(list(self.run_root.glob("task-*"))), 1)

    def test_concurrent_same_key_admits_only_one_task(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(
                pool.map(
                    lambda _: self.client.post("/api/v2/runs", json=self.body, headers=self.headers),
                    range(4),
                )
            )
        self.assertEqual(sorted(response.status_code for response in responses), [200, 200, 200, 202])
        run_ids = {response.json()["run_id"] for response in responses}
        self.assertEqual(len(run_ids), 1)
        self.wait_status(run_ids.pop(), "completed")
        self.assertEqual(len(list((self.run_root / ".tasks-v2").iterdir())), 1)
        self.assertEqual(len(list(self.run_root.glob("task-*"))), 1)

    def test_existing_run_directory_is_not_claimed_by_new_task(self):
        run_id = _task_id(SUBJECT, self.headers["Idempotency-Key"])
        (self.run_root / run_id).mkdir()
        response = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "idempotency_conflict")
        self.assertFalse((self.run_root / ".tasks-v2").exists())

    def test_running_cancellation_is_requested_then_applied_at_step_boundary(self):
        entered = Event()
        release = Event()
        real_run = AgentRuntime.run

        def blocked_run(runtime, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test worker did not release")
            return real_run(runtime, **kwargs)

        try:
            with patch.object(AgentRuntime, "run", blocked_run):
                submit = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
                self.assertEqual(submit.status_code, 202)
                run_id = submit.json()["run_id"]
                self.assertTrue(entered.wait(2))
                self.wait_status(run_id, "running")
                cancel = self.client.post(f"/api/v2/runs/{run_id}/cancel", headers=self.headers)
                self.assertEqual(cancel.status_code, 202)
                self.assertEqual(cancel.json()["status"], "running")
                self.assertTrue(cancel.json()["cancel_requested"])
                release.set()
                cancelled = self.wait_status(run_id, "cancelled")
                self.assertEqual(cancelled.json()["failure_type"], "RunCancelled")
                self.assertIsNone(cancelled.json()["links"]["summary"])
                state = json.loads((self.run_root / run_id / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(state["status"], "cancelled")
                again = self.client.post(f"/api/v2/runs/{run_id}/cancel", headers=self.headers)
                self.assertEqual(again.status_code, 200)
        finally:
            release.set()

    def test_queued_cancel_never_starts_second_run(self):
        entered = Event()
        release = Event()
        real_run = AgentRuntime.run

        def blocked_run(runtime, **kwargs):
            if kwargs["run_id"] == first_id:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test worker did not release")
            return real_run(runtime, **kwargs)

        first_id = _task_id(SUBJECT, self.headers["Idempotency-Key"])
        try:
            with patch.object(AgentRuntime, "run", blocked_run):
                first = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
                self.assertEqual(first.json()["run_id"], first_id)
                self.assertTrue(entered.wait(2))
                second_headers = {**self.headers, "Idempotency-Key": "task-lifecycle-key-0002"}
                second = self.client.post("/api/v2/runs", json=self.body, headers=second_headers)
                self.assertEqual(second.status_code, 202)
                second_id = second.json()["run_id"]
                self.assertEqual(second.json()["status"], "queued")
                cancelled = self.client.post(f"/api/v2/runs/{second_id}/cancel", headers=self.headers)
                self.assertEqual(cancelled.status_code, 200)
                self.assertEqual(cancelled.json()["status"], "cancelled")
                release.set()
                self.wait_status(first_id, "completed")
                self.wait_status(second_id, "cancelled")
                self.assertFalse((self.run_root / second_id).exists())
        finally:
            release.set()

    def test_auth_conflict_invalid_input_and_terminal_cancel_fail_closed(self):
        self.assertEqual(self.client.post("/api/v2/runs", json=self.body).status_code, 401)
        self.assertEqual(self.client.get("/api/v2/runs/task-" + "0" * 32).status_code, 401)
        self.assertEqual(self.client.post("/api/v2/runs/task-" + "0" * 32 + "/cancel").status_code, 401)
        self.assertEqual(list(self.run_root.iterdir()), [])

        invalid = self.client.post(
            "/api/v2/runs", json={**self.body, "source_path": "C:/secret"}, headers=self.headers
        )
        self.assertEqual(invalid.status_code, 422)
        wrong_request = self.client.post(
            "/api/v2/runs", json={**self.body, "request_id": "wrong-request"}, headers=self.headers
        )
        self.assertEqual(wrong_request.status_code, 422)
        self.assertEqual(list(self.run_root.iterdir()), [])

        first = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        run_id = first.json()["run_id"]
        changed = self.client.post(
            "/api/v2/runs", json={**self.body, "fixture_id": "alternate"}, headers=self.headers
        )
        self.assertEqual(changed.status_code, 409)
        self.assertEqual(changed.json()["error"]["code"], "idempotency_conflict")
        self.wait_status(run_id, "completed")
        terminal = self.client.post(f"/api/v2/runs/{run_id}/cancel", headers=self.headers)
        self.assertEqual(terminal.status_code, 409)
        self.assertEqual(terminal.json()["error"]["code"], "task_not_cancelable")
        self.assertEqual(self.client.get("/api/v2/runs/not-a-task", headers=self.headers).status_code, 404)

    def test_existing_key_replays_after_registered_file_changes_but_new_key_is_rejected(self):
        first = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        run_id = first.json()["run_id"]
        self.wait_status(run_id, "completed")
        self.fixture.write_bytes(self.fixture.read_bytes() + b"\n")
        replay = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["run_id"], run_id)
        new_key = self.client.post(
            "/api/v2/runs",
            json=self.body,
            headers={**self.headers, "Idempotency-Key": "task-lifecycle-key-0003"},
        )
        self.assertEqual(new_key.status_code, 409)
        self.assertEqual(new_key.json()["error"]["code"], "fixture_changed")
        self.assertEqual(len(list((self.run_root / ".tasks-v2").iterdir())), 1)

    def test_stale_record_is_interrupted_not_replayed(self):
        first = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
        run_id = first.json()["run_id"]
        self.wait_status(run_id, "completed")
        record_path = self.run_root / ".tasks-v2" / run_id / "task.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["status"] = "running"
        record["completed_at"] = None
        record["process_nonce"] = "0" * 32
        record_path.write_text(json.dumps(record), encoding="utf-8")
        restarted = create_app(
            ApiConfig(self.run_root, SUBJECT, TOKEN),
            submission=SubmissionConfig({"thesis": self.fixture}),
        )
        with TestClient(restarted) as client:
            status = client.get(f"/api/v2/runs/{run_id}", headers=self.headers)
            self.assertEqual(status.status_code, 200)
            self.assertEqual(status.json()["status"], "interrupted")
            self.assertEqual(status.json()["failure_type"], "RunInterrupted")
            retry = client.post("/api/v2/runs", json=self.body, headers=self.headers)
            self.assertEqual(retry.status_code, 200)
            self.assertEqual(retry.json()["status"], "interrupted")
            cancelled = client.post(f"/api/v2/runs/{run_id}/cancel", headers=self.headers)
            self.assertEqual(cancelled.status_code, 409)
        with self.assertRaises(RuntimeError):
            restarted.state.local_task_worker.executor.submit(lambda: None)
        restarted.state.local_task_worker.executor.shutdown(wait=True)

    def test_failed_worker_redacts_error_and_corrupt_record_fails_closed(self):
        with patch.object(AgentRuntime, "run", side_effect=RuntimeError("secret local path")):
            submitted = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
            self.assertEqual(submitted.status_code, 202)
            run_id = submitted.json()["run_id"]
            failed = self.wait_status(run_id, "failed")
        self.assertEqual(failed.json()["failure_type"], "RuntimeError")
        self.assertNotIn("secret local path", failed.text)
        self.assertIsNone(failed.json()["links"]["summary"])

        record_path = self.run_root / ".tasks-v2" / run_id / "task.json"
        record_path.write_text('{"contract_type":"quantagent.run_status.v2"}', encoding="utf-8")
        corrupt = self.client.get(f"/api/v2/runs/{run_id}", headers=self.headers)
        self.assertEqual(corrupt.status_code, 409)
        self.assertEqual(corrupt.json()["error"]["code"], "artifact_integrity_error")

    def test_forged_cancel_exception_without_cancelled_run_state_is_failed(self):
        with patch.object(AgentRuntime, "run", side_effect=RunCancelled("not host requested")):
            submitted = self.client.post("/api/v2/runs", json=self.body, headers=self.headers)
            self.assertEqual(submitted.status_code, 202)
            failed = self.wait_status(submitted.json()["run_id"], "failed")
        self.assertEqual(failed.json()["failure_type"], "RunCancelled")
        self.assertFalse(failed.json()["cancel_requested"])

    def test_bounded_admission_rejects_ninth_inflight_task(self):
        entered = Event()
        release = Event()
        real_run = AgentRuntime.run

        def blocked_run(runtime, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test worker did not release")
            return real_run(runtime, **kwargs)

        try:
            with patch.object(AgentRuntime, "run", blocked_run):
                run_ids = []
                for index in range(8):
                    headers = {**self.headers, "Idempotency-Key": f"task-capacity-key-{index:04d}"}
                    response = self.client.post("/api/v2/runs", json=self.body, headers=headers)
                    self.assertEqual(response.status_code, 202, response.text)
                    run_ids.append(response.json()["run_id"])
                self.assertTrue(entered.wait(2))
                ninth = self.client.post(
                    "/api/v2/runs",
                    json=self.body,
                    headers={**self.headers, "Idempotency-Key": "task-capacity-key-0008"},
                )
                self.assertEqual(ninth.status_code, 429)
                self.assertEqual(ninth.json()["error"]["code"], "task_capacity_reached")
                self.assertEqual(len(list((self.run_root / ".tasks-v2").iterdir())), 8)
                release.set()
                for run_id in run_ids:
                    self.wait_status(run_id, "completed")
        finally:
            release.set()

    def test_read_only_app_keeps_v2_routes_disabled(self):
        with TestClient(create_app(ApiConfig(self.run_root, SUBJECT, TOKEN))) as client:
            self.assertEqual(client.post("/api/v2/runs", json=self.body, headers=self.headers).status_code, 404)
            self.assertEqual(client.get("/api/v2/runs/task-" + "0" * 32, headers=self.headers).status_code, 404)


if __name__ == "__main__":
    unittest.main()
