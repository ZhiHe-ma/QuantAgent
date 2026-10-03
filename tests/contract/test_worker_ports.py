"""Worker-service injection retains real host IO, result and startup boundaries."""
from dataclasses import FrozenInstanceError
import importlib
import inspect
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests.support.paths import ROOT


class WorkerPortTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def ports(self):
        self.assertTrue((ROOT / "quantagent_platform/worker_ports.py").is_file(),
                        "missing public worker-service contract")
        return importlib.import_module("quantagent_platform.worker_ports")

    def preserve_factory(self, ports):
        original = ports.get_worker_services_factory()
        self.addCleanup(ports.configure_worker_services, original)

    def test_injected_reader_receives_bounds_and_preserves_read_failures(self):
        ports = self.ports()
        self.preserve_factory(ports)
        runtime = importlib.import_module("quantagent_platform.isolated_runtime")
        from quantagent_platform.plugins import PluginError

        class TaggedReader(runtime.LocalWorkerServices):
            def read_bounded(self, path, max_bytes, label):
                return super().read_bounded(path, max_bytes, label) + f"|{max_bytes}|{label}".encode()

        ports.configure_worker_services(TaggedReader)
        path = self.root / "data.bin"
        path.write_bytes(b"abc")
        self.assertEqual(b"abc|3|sample", ports.read_bounded(path, 3, "sample"))
        for limit, message in ((2, "sample exceeds 2 bytes"), (0, "sample max_bytes must be positive")):
            with self.subTest(limit=limit), self.assertRaisesRegex(PluginError, message):
                ports.read_bounded(path, limit, "sample")
        with self.assertRaisesRegex(PluginError, "cannot read sample"):
            ports.read_bounded(self.root / "absent", 3, "sample")

    def test_injected_executor_receives_all_keywords_and_propagates_owner_error(self):
        ports = self.ports()
        self.preserve_factory(ports)
        runtime = importlib.import_module("quantagent_platform.isolated_runtime")
        from quantagent_platform.plugins import PluginError, RunContext

        class TaggedExecutor(runtime.LocalWorkerServices):
            def execute_json_worker(self, context, **options):
                if options["display_name"] == "failure":
                    raise PluginError("owner worker failure")
                result = super().execute_json_worker(context, **options)
                result.response["forwarded"] = {
                    "run_id": context.run_id, "display_name": options["display_name"],
                    "file_prefix": options["file_prefix"], "timeout": options["timeout_seconds"],
                    "response_limit": options["max_response_bytes"], "log_limit": options["max_log_bytes"],
                }
                return result

        ports.configure_worker_services(TaggedExecutor)
        data = self.root / "data.bin"
        data.write_bytes(b"abc")
        worker = ROOT / "tests/support/fakes/fake_qlib_worker.py"
        context = RunContext("port-run", self.root, (self.root, ROOT), (self.root,), True)
        request = {"protocol_version": "quantagent.qlib_worker.v1", "request_id": "port-request",
                   "operation": "factor_research", "data_path": str(data),
                   "data_sha256": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                   "columns": {"datetime": "datetime", "instrument": "instrument", "factor": "factor", "label": "label"},
                   "min_rows_per_date": 3}
        options = dict(display_name="injected", file_prefix="port-worker",
                       python_executable=Path(sys.executable), worker_path=worker, request=request,
                       timeout_seconds=30, max_response_bytes=4096, max_log_bytes=512)
        result = ports.execute_json_worker(context, **options)
        self.assertEqual({"run_id": "port-run", "display_name": "injected", "file_prefix": "port-worker",
                          "timeout": 30, "response_limit": 4096, "log_limit": 512}, result.response["forwarded"])
        self.assertEqual(request, json.loads((self.root / "port-worker-request.json").read_text(encoding="utf-8")))
        self.assertEqual("port-request", result.response["request_id"])
        self.assertEqual(request["data_sha256"], result.response["result"]["metadata"]["data_sha256"])
        self.assertEqual(0, result.returncode)
        self.assertEqual("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                         result.stdout_sha256)
        with self.assertRaisesRegex(PluginError, "owner worker failure"):
            ports.execute_json_worker(context, **{**options, "display_name": "failure"})

    def test_original_execution_alias_and_function_signatures_remain_compatible(self):
        ports = self.ports()
        runtime = importlib.import_module("quantagent_platform.isolated_runtime")
        self.assertIs(runtime.WorkerExecution, ports.WorkerExecution)
        result = runtime.WorkerExecution({"ok": True}, 0, "stdout", "stderr")
        self.assertIsInstance(result, ports.WorkerExecution)
        self.assertEqual(({"ok": True}, 0, "stdout", "stderr"),
                         (result.response, result.returncode, result.stdout_sha256, result.stderr_sha256))
        with self.assertRaises(FrozenInstanceError):
            result.returncode = 1
        for name in ("read_bounded", "execute_json_worker"):
            self.assertEqual(inspect.signature(getattr(runtime, name)), inspect.signature(getattr(ports, name)))

    def test_startup_binding_is_lazy_and_bad_factory_does_not_replace_it(self):
        ports = self.ports()
        self.preserve_factory(ports)
        bootstrap = importlib.import_module("quantagent_platform.worker_bootstrap")

        def not_constructed_during_startup():
            raise RuntimeError("service is constructed only when consumed")

        with patch.object(bootstrap, "LocalWorkerServices", not_constructed_during_startup), \
             patch.object(Path, "read_bytes", side_effect=AssertionError("startup IO")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("startup write")), \
             patch.object(subprocess, "run", side_effect=AssertionError("startup process")):
            bootstrap.install_worker_services()
        with self.assertRaisesRegex(TypeError, "factory must be callable"):
            ports.configure_worker_services(None)
        with self.assertRaisesRegex(RuntimeError, "service is constructed only when consumed"):
            ports.read_bounded(self.root / "unopened", 3, "sample")

    def test_ports_and_plugins_reload_without_concrete_runtime_and_fail_closed_unbound(self):
        self.ports()
        code = """
import importlib, importlib.abc, json, sys
from pathlib import Path
import quantagent_platform
for name in ('worker_ports', 'qlib_plugins', 'bt_plugins', 'isolated_runtime'):
    sys.modules.pop('quantagent_platform.' + name, None)
class BlockRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'quantagent_platform.isolated_runtime' or fullname.split('.')[0] in {'qlib','bt','pandas','numpy'}:
            raise AssertionError('contract/plugin reload reached concrete runtime or SDK: ' + fullname)
sys.meta_path.insert(0, BlockRuntime())
p = importlib.import_module('quantagent_platform.worker_ports')
q = importlib.import_module('quantagent_platform.qlib_plugins')
b = importlib.import_module('quantagent_platform.bt_plugins')
try:
    p.read_bounded(Path('unopened'), 3, 'sample')
except RuntimeError as exc:
    assert 'not been configured at startup' in str(exc)
else:
    raise AssertionError('unbound services silently executed')
print(json.dumps({'owner':p.WorkerExecution.__module__, 'same_read':q.read_bounded is p.read_bounded and b.read_bounded is p.read_bounded,
                  'runtime_reloaded':'quantagent_platform.isolated_runtime' in sys.modules, 'unbound_rejected':True}))
"""
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"owner": "quantagent_platform.worker_ports", "same_read": True,
                          "runtime_reloaded": False, "unbound_rejected": True}, json.loads(result.stdout))

    def test_original_default_recipes_consume_injected_services(self):
        ports = self.ports()
        self.preserve_factory(ports)
        runtime = importlib.import_module("quantagent_platform.isolated_runtime")
        from quantagent_platform import RecipeRunner

        class TaggedWorker(runtime.LocalWorkerServices):
            def execute_json_worker(self, context, **options):
                result = super().execute_json_worker(context, **options)
                result.response["result"]["metadata"]["injected_service"] = "owned-worker-port"
                return result

        ports.configure_worker_services(TaggedWorker)
        for recipe, fixture, worker, options, packet_file in (
            ("qlib_factor_research.json", "sample_qlib_factor.csv", "fake_qlib_worker.py", {}, "01-run-qlib-factor-research.json"),
            ("bt_portfolio_backtest.json", "sample_bt_panel.csv", "fake_bt_worker.py",
             {"price_semantics": "synthetic_close"}, "01-run-bt-portfolio-backtest.json"),
        ):
            with self.subTest(recipe=recipe):
                data = self.root / fixture
                shutil.copyfile(ROOT / "tests/fixtures" / fixture, data)
                worker_options = {"python_executable": sys.executable,
                                  "worker_path": str(ROOT / "tests/support/fakes" / worker),
                                  "timeout_seconds": 30, **options}
                params = {"source_path": str(data), "qlib_options": worker_options, "backtest_options": worker_options}
                result = RecipeRunner().run(
                    RecipeRunner.load_recipe(ROOT / "recipes" / recipe), params=params,
                    output_dir=self.root / "runs", run_id=Path(recipe).stem,
                    allowed_read_roots=[self.root, ROOT, Path(sys.executable).resolve().parent],
                    allowed_permissions={"filesystem:read", "filesystem:write", "process:spawn"})
                self.assertEqual("completed", result.status)
                packet = json.loads((result.run_dir / packet_file).read_text(encoding="utf-8"))
                self.assertEqual("owned-worker-port", packet["metadata"]["injected_service"])


if __name__ == "__main__":
    unittest.main()
