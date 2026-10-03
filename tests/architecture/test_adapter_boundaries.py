"""Inspect owned adapter boundaries without importing or executing product modules."""
from pathlib import Path
import sys
import unittest

from tools.architecture.graph import collect
from tools.architecture.policy import IO_PACKAGES

ROOT = Path(__file__).resolve().parents[2]


class AdapterBoundaryTests(unittest.TestCase):
    def test_adapters_do_not_import_quality_adapter(self):
        paths = [f"quantagent_platform/{name}.py" for name in
                 ("bt_plugins", "qlib_plugins", "daily_plugins", "outcome_plugins", "builtin_plugins")]
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8") for path in paths})
        for name, module in graph["modules"].items():
            if name.endswith(".builtin_plugins"):
                continue
            with self.subTest(adapter=name):
                self.assertFalse(any(edge["target"] == "quantagent_platform.builtin_plugins"
                                     for edge in module["imports"]),
                                 f"{name} imports the concrete quality adapter")
                self.assertFalse(any(edge["dynamic"] for edge in module["imports"]), name)

    def test_signal_report_contract_has_no_io_or_local_dependencies(self):
        path = "quantagent_platform/signal_report_contracts.py"
        self.assertTrue((ROOT / path).is_file(), "missing owned signal/report contract")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8")})
        for edge in graph["modules"]["quantagent_platform.signal_report_contracts"]["imports"]:
            root = edge["target"].split(".")[0]
            self.assertFalse(edge["dynamic"])
            self.assertIn(root, sys.stdlib_module_names)
            self.assertNotIn(root, IO_PACKAGES)

    def test_worker_adapters_use_ports_and_contracts_have_no_io(self):
        paths = ["quantagent_platform/bt_plugins.py", "quantagent_platform/qlib_plugins.py"]
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8") for path in paths})
        for name, module in graph["modules"].items():
            with self.subTest(adapter=name):
                self.assertFalse(any(edge["target"] == "quantagent_platform.isolated_runtime"
                                     for edge in module["imports"]), name)
        path = "quantagent_platform/worker_ports.py"
        self.assertTrue((ROOT / path).is_file(), "missing owned worker ports")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8")})
        for edge in graph["modules"]["quantagent_platform.worker_ports"]["imports"]:
            self.assertFalse(edge["dynamic"])
            if edge["target"].startswith("quantagent_platform"):
                self.assertEqual("quantagent_platform.plugins", edge["target"])
            else:
                root = edge["target"].split(".")[0]
                self.assertIn(root, sys.stdlib_module_names)
                self.assertNotIn(root, IO_PACKAGES)


if __name__ == "__main__":
    unittest.main()
