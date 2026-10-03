"""Public default construction, explicit injection and curated catalog compatibility."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from quantagent_platform import AgentRuntime, RecipeRunner
from quantagent_platform import runner
from quantagent_platform.plugins import PluginError, PluginRegistry
from tools.architecture.graph import collect

ROOT = Path(__file__).resolve().parents[2]
# Public manifest rows captured at 76382aa; changing this needs a catalog review.
CATALOG_SHA256 = "198b0a45ab704408f76b56a47faec76578e3546f320b7d643c62457540c5d51d"
EXPORTS = [
    "AgentCatalog", "AgentError", "AgentRuntime", "ContractError", "DataPacket",
    "ManifestError", "RecipeError", "RecipeRunner", "RunCancelled",
    "ResolvedAgentPlan", "RunResult", "default_registry",
]


def catalog_digest(registry):
    return hashlib.sha256(json.dumps(
        registry.catalog(), sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


class RunnerCompositionTests(unittest.TestCase):
    def test_runner_depends_only_on_packets_and_plugin_ports(self):
        path = "quantagent_platform/runner.py"
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8")})
        imports = graph["modules"]["quantagent_platform.runner"]["imports"]
        self.assertEqual(
            {"quantagent_platform.contracts", "quantagent_platform.plugins"},
            {edge["target"] for edge in imports if edge["target"].startswith("quantagent_platform")},
        )
        self.assertFalse(any(edge["dynamic"] for edge in imports))

    def test_explicit_registry_is_used_even_if_it_is_falsey(self):
        class EmptyRegistry(PluginRegistry):
            def __bool__(self):
                return False

        registry = EmptyRegistry()
        with patch.object(runner, "default_registry", side_effect=AssertionError("must not assemble defaults")):
            self.assertIs(registry, RecipeRunner(registry).registry)

    def test_default_registry_is_fresh_and_keeps_catalog(self):
        bootstrap = importlib.import_module("quantagent_platform.bootstrap")
        registries = [bootstrap.build_default_registry(), runner.default_registry(), RecipeRunner().registry]
        for registry in registries:
            self.assertEqual(CATALOG_SHA256, catalog_digest(registry))
            self.assertEqual(29, len(registry.catalog()))
        self.assertEqual(3, len({id(registry) for registry in registries}))
        first_id = registries[0].catalog()[0]["plugin_id"]
        self.assertIsNot(registries[0].get(first_id), registries[1].get(first_id))
        self.assertEqual(CATALOG_SHA256, catalog_digest(AgentRuntime().runner.registry))

    def test_startup_injection_is_lazy_and_explicit_registry_takes_precedence(self):
        bootstrap = importlib.import_module("quantagent_platform.bootstrap")
        self.addCleanup(bootstrap.install_default_registry)
        calls = []

        def factory():
            calls.append("built")
            return PluginRegistry()

        runner.configure_default_registry(factory)
        self.assertEqual([], calls)
        explicit = PluginRegistry()
        self.assertIs(explicit, RecipeRunner(explicit).registry)
        self.assertEqual([], calls)
        first, second = runner.default_registry(), runner.default_registry()
        self.assertIsNot(first, second)
        self.assertEqual(["built", "built"], calls)
        with self.assertRaisesRegex(TypeError, "factory must be callable"):
            runner.configure_default_registry(None)
        self.assertEqual([], runner.default_registry().catalog())

    def test_package_startup_does_not_read_curated_catalog(self):
        code = """
from pathlib import Path
from unittest.mock import patch
original = Path.read_text
def checked_read(path, *args, **kwargs):
    if path.name == 'catalog.json' and path.parent.name == 'plugin_catalog':
        raise AssertionError('startup must only inject the factory')
    return original(path, *args, **kwargs)
with patch.object(Path, 'read_text', checked_read):
    from quantagent_platform import RecipeRunner
    from quantagent_platform.plugins import PluginRegistry
    registry = PluginRegistry()
    assert RecipeRunner(registry).registry is registry
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_public_python_exports_and_default_calls_work_in_fresh_processes(self):
        code = (
            "import importlib,json; importlib.import_module({first!r}); "
            "import quantagent_platform as p; from quantagent_platform.runner import default_registry; "
            "print(json.dumps({{'exports':p.__all__,'version':p.__version__,"
            "'same_factory':p.default_registry is default_registry,"
            "'runner_count':len(p.RecipeRunner().registry.catalog()),"
            "'agent_count':len(p.AgentRuntime().runner.registry.catalog())}}))"
        )
        for first in ("quantagent_platform.runner", "quantagent_platform.manifests", "quantagent_platform.bootstrap"):
            with self.subTest(first=first):
                result = subprocess.run([sys.executable, "-c", code.format(first=first)], cwd=ROOT,
                                        capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual({"exports": EXPORTS, "version": "0.5.0", "same_factory": True,
                                  "runner_count": 29, "agent_count": 29}, json.loads(result.stdout))

    def test_cli_catalog_matches_public_default_registry(self):
        result = subprocess.run([sys.executable, "-m", "quantagent_platform", "catalog", "--json"],
                                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(runner.default_registry().catalog(), json.loads(result.stdout))

    def test_curated_catalog_missing_or_mismatched_still_fails(self):
        bootstrap = importlib.import_module("quantagent_platform.bootstrap")
        original = json.loads((ROOT / "plugin_catalog/catalog.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "plugin_catalog/catalog.json"
            catalog_path.parent.mkdir()
            with patch.object(bootstrap, "__file__", str(root / "quantagent_platform/bootstrap.py")):
                with self.assertRaisesRegex(PluginError, "cannot load curated plugin catalog"):
                    bootstrap.build_default_registry()
                for field, message in (("version", "catalog version mismatch"), ("status", "catalog status mismatch")):
                    data = json.loads(json.dumps(original))
                    for row in data["plugins"]:
                        row[field] = "incompatible"
                    catalog_path.write_text(json.dumps(data), encoding="utf-8")
                    with self.subTest(field=field), self.assertRaisesRegex(PluginError, message):
                        bootstrap.build_default_registry()
                catalog_path.write_text('{"plugins": []}', encoding="utf-8")
                with self.assertRaisesRegex(PluginError, "plugin is not present in curated catalog"):
                    bootstrap.build_default_registry()


if __name__ == "__main__":
    unittest.main()
