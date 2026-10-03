import ast
import unittest

from tests.support.paths import ROOT
from tools.architecture.graph import collect
from tools.architecture.policy import IO_PACKAGES


class RecoveryBoundaryTests(unittest.TestCase):
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
