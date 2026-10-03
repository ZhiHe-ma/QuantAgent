import ast
import unittest

from tests.support.paths import ROOT
from tools.architecture.graph import collect
from tools.architecture.policy import IO_PACKAGES


class RecoveryBoundaryTests(unittest.TestCase):
    def test_recovery_workflows_use_only_public_pure_dependencies(self):
        expected = {"quantagent_platform.daily_workflow", "quantagent_platform.legacy_ports",
                    "quantagent_platform.legacy_daily_recovery", "quantagent_platform.legacy_monitor_recovery",
                    "quantagent_platform.recovery.contracts", "quantagent_platform.recovery.rules"}
        for name in ("legacy_daily_recovery", "legacy_monitor_recovery", "legacy_recovery_actions"):
            path = "quantagent_platform/"+name+".py"
            text = (ROOT/path).read_text(encoding="utf-8")
            graph = collect({path: text})
            for edge in next(iter(graph["modules"].values()))["imports"]:
                self.assertFalse(edge["dynamic"])
                self.assertNotIn(edge["target"].split(".")[0], IO_PACKAGES)
                if edge["target"].startswith("quantagent_platform"):
                    self.assertIn(edge["target"], expected)
                    self.assertFalse(edge["member"].startswith("_"))
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"open", "eval", "exec", "__import__"})
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "ports":
                    self.assertFalse(node.attr.startswith("_"))

    def test_recovery_core_is_pure_and_storage_is_not_imported_by_core(self):
        for name in ("contracts", "rules"):
            path = "quantagent_platform/recovery/" + name + ".py"
            self.assertTrue((ROOT / path).is_file(), "missing recovery core")
            text = (ROOT / path).read_text(encoding="utf-8")
            graph = collect({path: text})
            for edge in next(iter(graph["modules"].values()))["imports"]:
                self.assertFalse(edge["dynamic"])
                self.assertNotIn(edge["target"].split(".")[0], IO_PACKAGES)
                self.assertNotIn("sqlite_store", edge["target"])
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, {"open", "eval", "exec", "__import__"})
