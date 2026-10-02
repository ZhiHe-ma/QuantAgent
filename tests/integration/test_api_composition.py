"""API assembly compatibility, startup boundaries and authorized public storage."""
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from quantagent_platform.result_api import AccessDenied, ApiConfig, ArtifactIntegrityError, create_app
from quantagent_platform.submission_api import SubmissionConfig
from tests.support.api_samples import api_contract_snapshot
from tests.support.paths import ROOT


TOKEN = "synthetic-api-token-at-least-32-chars"


class ApiCompositionTests(unittest.TestCase):
    def test_original_http_contract_fixture_remains_identical(self):
        expected = json.loads((ROOT / "tests/fixtures/api_route_compatibility.json").read_text(encoding="utf-8"))
        self.assertEqual(expected["contracts"], api_contract_snapshot())

    def test_legacy_factory_passes_explicit_falsey_submission_to_startup_binding(self):
        ports = importlib.import_module("quantagent_platform.api_ports")
        previous = ports.get_api_app_factory()
        calls = []
        application, config = object(), object()

        class FalseySubmission:
            def __bool__(self):
                return False

        submission = FalseySubmission()

        def factory(config, submission):
            calls.append((config, submission))
            return application

        try:
            ports.configure_api_app_factory(factory)
            self.assertIs(application, create_app(config, submission=submission))
            self.assertIs(application, create_app(config))
            self.assertEqual([(config, submission), (config, None)], calls)
            with self.assertRaises(TypeError):
                ports.configure_api_app_factory(None)
            self.assertIs(factory, ports.get_api_app_factory())
        finally:
            ports.configure_api_app_factory(previous)

    def test_core_startup_needs_no_http_stack_or_runtime_io(self):
        code = """
import importlib.abc
import sys
from pathlib import Path
from unittest.mock import patch
class BlockHttp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'fastapi', 'pydantic', 'uvicorn', 'httpx2'}:
            raise ImportError('optional HTTP stack loaded by core: ' + fullname)
sys.meta_path.insert(0, BlockHttp())
with patch.object(Path, 'mkdir', side_effect=AssertionError('startup mkdir')), \
     patch('sqlite3.connect', side_effect=AssertionError('startup database')), \
     patch('concurrent.futures.ThreadPoolExecutor.__init__', side_effect=AssertionError('startup worker')):
    import quantagent_platform
    from quantagent_platform.api_ports import get_api_app_factory
    assert callable(get_api_app_factory())
    assert len(quantagent_platform.__all__) == 12
    assert not any(name.split('.')[0] in {'fastapi', 'pydantic', 'uvicorn', 'httpx2'} for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_public_storage_keeps_authorization_integrity_and_size_limits(self):
        storage = importlib.import_module("quantagent_platform.api_storage")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "failed-run"
            run.mkdir()
            state = {"run_id": "failed-run", "recipe_id": "thesis-tracker", "recipe_version": "1.0.0",
                     "status": "failed", "started_at": "2026-09-22T00:00:00+00:00",
                     "completed_at": "2026-09-22T00:00:01+00:00", "offline": True,
                     "steps": [], "error": {"type": "SyntheticFailure"}}
            raw = json.dumps(state).encode("utf-8")
            path = run / "run.json"
            path.write_bytes(raw)
            store = storage.ResultStore(root, owner_subject="owner")
            with self.assertRaises(AccessDenied):
                store.load_state("failed-run", "other-owner")
            loaded_dir, loaded = store.load_state("failed-run", "owner")
            self.assertEqual(run.resolve(), loaded_dir)
            self.assertEqual(state, loaded)
            self.assertEqual("SyntheticFailure", store.summary_from_state("failed-run", loaded).failure_type)
            self.assertEqual(raw, storage.read_bounded(path, len(raw)))
            for unsafe, limit in ((path, len(raw) - 1), (run, len(raw)), (root / "missing", len(raw))):
                with self.assertRaises(ArtifactIntegrityError):
                    storage.read_bounded(unsafe, limit)
            self.assertEqual(raw, path.read_bytes())

    def test_falsey_enabled_config_still_installs_original_submission_routes(self):
        class FalseyConfig(SubmissionConfig):
            def __bool__(self):
                return False

        with tempfile.TemporaryDirectory() as directory:
            app = create_app(ApiConfig(Path(directory), "owner", TOKEN),
                             submission=FalseyConfig({"thesis": ROOT / "tests/fixtures/sample_thesis_review.json"}))
            with TestClient(app) as client:
                self.assertEqual("v2", client.get("/healthz").json()["api_version"])
                for url in ("/api/v1/runs", "/api/v2/runs"):
                    self.assertEqual(401, client.post(url, json={}).status_code)

    def test_explicit_builder_matches_schema_and_closes_its_worker_once(self):
        bootstrap = importlib.import_module("quantagent_platform.api_bootstrap")
        expected = json.loads((ROOT / "tests/fixtures/api_route_compatibility.json").read_text(encoding="utf-8"))["contracts"]
        with tempfile.TemporaryDirectory() as directory:
            config = ApiConfig(Path(directory), "owner", TOKEN)
            readonly = bootstrap.build_api_app(config)
            self.assertEqual(expected["read_only"]["openapi"], readonly.openapi())
            self.assertFalse(hasattr(readonly.state, "local_task_worker"))
            enabled = bootstrap.build_api_app(config, SubmissionConfig({"thesis": ROOT / "tests/fixtures/sample_thesis_review.json"}))
            self.assertEqual(expected["enabled"]["openapi"], enabled.openapi())
            worker = enabled.state.local_task_worker
            with patch.object(worker, "shutdown", wraps=worker.shutdown) as shutdown:
                with TestClient(enabled) as client:
                    self.assertEqual(200, client.get("/healthz").status_code)
                shutdown.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
