"""AST-only API dependency checks; no business imports or networking."""
import json
from pathlib import Path
import unittest

from tools.architecture.graph import collect
from tools.architecture.policy import inspect

ROOT = Path(__file__).resolve().parents[2]
ENDPOINTS = {"quantagent_platform.result_api", "quantagent_platform.submission_api",
             "quantagent_platform.task_lifecycle_api"}


class ApiBoundaryTests(unittest.TestCase):
    def test_endpoint_modules_have_no_mutual_imports_or_private_store_access(self):
        registry = json.loads((ROOT / "docs/architecture/components.json").read_text(encoding="utf-8"))
        result = inspect(ROOT, registry)
        self.assertEqual([], result["cycles"])
        graph = collect({name.replace(".", "/") + ".py":
                         (ROOT / (name.replace(".", "/") + ".py")).read_text(encoding="utf-8")
                         for name in ENDPOINTS})
        for module in graph["modules"].values():
            self.assertFalse(any(edge["target"] in ENDPOINTS for edge in module["imports"]))
        for name in ENDPOINTS:
            source = (ROOT / (name.replace(".", "/") + ".py")).read_text(encoding="utf-8")
            self.assertNotIn("store._load_state", source)
            self.assertNotIn("store._summary_from_state", source)

    def test_shared_contract_and_factory_port_do_not_depend_on_http_execution(self):
        paths = ["quantagent_platform/api_contracts.py", "quantagent_platform/api_ports.py"]
        for path in paths:
            self.assertTrue((ROOT / path).is_file(), f"missing contract: {path}")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8") for path in paths})
        for module in graph["modules"].values():
            self.assertFalse(any(edge["dynamic"] for edge in module["imports"]))
            self.assertFalse(any(edge["target"].startswith("quantagent_platform") or
                                 edge["target"].split(".")[0] in
                                 {"fastapi", "sqlite3", "subprocess", "uvicorn"}
                                 for edge in module["imports"]))


if __name__ == "__main__":
    unittest.main()
