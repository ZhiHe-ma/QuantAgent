"""Read legacy boundaries without executing business code or contacting services."""
import ast
from pathlib import Path
import sys
import unittest

from tools.architecture.graph import collect
from tools.architecture.policy import IO_PACKAGES

ROOT = Path(__file__).resolve().parents[2]


class LegacyBoundaryTests(unittest.TestCase):
    def test_entry_has_no_concrete_audit_daily_domain_or_dynamic_imports(self):
        graph = collect({"agent_engine.py": (ROOT / "agent_engine.py").read_text(encoding="utf-8")})
        for edge in graph["modules"]["agent_engine"]["imports"]:
            with self.subTest(target=edge["target"]):
                self.assertNotIn(edge["target"], {"signal_audit", "quantagent_platform.daily_workflow"})
                self.assertFalse(edge["dynamic"])

    def test_legacy_ports_are_independent_of_io_and_product_implementations(self):
        path = "quantagent_platform/legacy_ports.py"
        self.assertTrue((ROOT / path).is_file(), "missing owned legacy ports")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8")})
        for edge in graph["modules"]["quantagent_platform.legacy_ports"]["imports"]:
            self.assertFalse(edge["dynamic"])
            if edge["target"] in {"signal_audit_contracts", "quantagent_platform.recovery.contracts"}:
                continue
            root = edge["target"].split(".")[0]
            self.assertIn(root, sys.stdlib_module_names)
            self.assertNotIn(root, IO_PACKAGES)
        path = "signal_audit_contracts.py"
        self.assertTrue((ROOT / path).is_file(), "missing standalone audit contract")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8")})
        for edge in graph["modules"]["signal_audit_contracts"]["imports"]:
            self.assertFalse(edge["dynamic"])
            self.assertIn(edge["target"].split(".")[0], sys.stdlib_module_names)
            self.assertNotIn(edge["target"].split(".")[0], IO_PACKAGES)

    def test_workflows_use_public_ports_without_file_or_adapter_access(self):
        path = "quantagent_platform/legacy_workflows.py"
        self.assertTrue((ROOT / path).is_file(), "missing owned legacy workflows")
        text = (ROOT / path).read_text(encoding="utf-8")
        graph = collect({path: text})
        for edge in graph["modules"]["quantagent_platform.legacy_workflows"]["imports"]:
            self.assertFalse(edge["dynamic"])
            self.assertNotIn(edge["target"].split(".")[0], IO_PACKAGES)
            if edge["target"].startswith("quantagent_platform"):
                self.assertIn(edge["target"], {"quantagent_platform.legacy_ports", "quantagent_platform.daily_workflow"})
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "__import__", "eval", "exec"})
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ports":
                self.assertFalse(node.attr.startswith("_"), node.attr)


if __name__ == "__main__":
    unittest.main()
