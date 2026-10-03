"""Fixed API contracts from temporary synthetic inputs; no network or model calls."""
import json
from pathlib import Path
import shutil
import tempfile

from fastapi.testclient import TestClient
from quantagent_platform import result_api, submission_api, task_lifecycle_api
from tests.support.paths import ROOT


ERROR_NAMES = {
    "result": ("ReadApiError", "AuthenticationRequired", "AccessDenied", "RunNotFound",
               "ResultUnavailable", "ArtifactIntegrityError"),
    "submission": ("InvalidSubmission", "SubmissionTooLarge", "IdempotencyConflict",
                   "SubmissionPending", "FixtureChanged", "ExecutionFailed"),
    "task": ("TaskNotFound", "TaskCapacity", "TaskNotCancelable", "TaskInterrupted"),
}


def api_contract_snapshot():
    """Record exact read-only/enabled OpenAPI and nonsensitive HTTP errors."""
    contracts = {"errors": {}}
    for label, module in (("result", result_api), ("submission", submission_api),
                          ("task", task_lifecycle_api)):
        contracts["errors"][label] = {
            name: {"status": getattr(module, name).status_code,
                   "code": getattr(module, name).code,
                   "message": getattr(module, name).public_message,
                   "headers": getattr(module, name).headers}
            for name in ERROR_NAMES[label]
        }
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        runs = root / "runs"
        runs.mkdir()
        fixture = root / "review.json"
        shutil.copyfile(ROOT / "tests/fixtures/sample_thesis_review.json", fixture)
        config = result_api.ApiConfig(runs, "synthetic-owner", "synthetic-api-token-at-least-32-chars")
        for label, submission in (("read_only", None),
                                  ("enabled", submission_api.SubmissionConfig({"thesis": fixture}))):
            app = result_api.create_app(config, submission=submission)
            contracts[label] = {"openapi": app.openapi(), "responses": {}}
            with TestClient(app) as client:
                for key, url, headers in (
                    ("health", "/healthz", {}),
                    ("unauthenticated", "/api/v1/runs/missing", {}),
                    ("missing", "/api/v1/runs/missing", {"Authorization": f"Bearer {config.bearer_token}"}),
                ):
                    response = client.get(url, headers=headers)
                    contracts[label]["responses"][key] = {
                        "status": response.status_code, "body": response.json(),
                        "headers": {name: response.headers[name] for name in
                                    ("cache-control", "www-authenticate", "content-type")
                                    if name in response.headers},
                    }
    # Return an independent JSON value, never fixture paths or credentials.
    return json.loads(json.dumps(contracts))
