"""P5 source boundaries; AST only, no business imports or network."""
import json
from pathlib import Path
import unittest

from tools.architecture.graph import collect
from tools.architecture.policy import inspect

ROOT = Path(__file__).resolve().parents[2]


class P5ArchitectureTests(unittest.TestCase):
    def test_d002_concrete_and_private_dependencies_are_gone(self):
        registry = json.loads((ROOT / "docs/architecture/components.json").read_text(encoding="utf-8"))
        violations = inspect(ROOT, registry)["violations"]
        blocked_sources = {"quantagent_platform.p5_handoff", "quantagent_platform.p5_review",
                           "quantagent_platform.p5_coordinator", "quantagent_platform.p5_worker",
                           "quantagent_platform.p5_plugins"}
        self.assertEqual([], [v for v in violations if v["source"] in blocked_sources])

    def test_p5_ports_and_sec_identities_only_use_stable_contracts(self):
        paths = ["quantagent_platform/p5_ports.py", "quantagent_platform/sec_source_identities.py"]
        for path in paths:
            self.assertTrue((ROOT / path).is_file(), f"missing pure contract: {path}")
        graph = collect({path: (ROOT / path).read_text(encoding="utf-8") for path in paths})
        for module in graph["modules"].values():
            self.assertFalse(any(edge["dynamic"] for edge in module["imports"]))
            self.assertLessEqual({edge["target"] for edge in module["imports"]
                                  if edge["target"].startswith("quantagent_platform")},
                                 {"quantagent_platform.contracts"})


if __name__ == "__main__":
    unittest.main()
