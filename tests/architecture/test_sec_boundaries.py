"""AST-only SEC boundaries: no product imports, execution or networking."""
from pathlib import Path
import unittest

from tools.architecture.graph import collect

ROOT = Path(__file__).resolve().parents[2]


class SecBoundaryTests(unittest.TestCase):
    def test_response_contract_is_standalone_and_normalization_has_no_client_dependency(self):
        paths = ["quantagent_platform/sec_response_contracts.py",
                 "quantagent_platform/sec_contracts.py",
                 "quantagent_platform/sec_source_identities.py"]
        self.assertTrue((ROOT / paths[0]).is_file(), "missing pure SEC response contract")
        graph = collect({p: (ROOT / p).read_text(encoding="utf-8") for p in paths})
        for name, module in graph["modules"].items():
            for edge in module["imports"]:
                self.assertFalse(edge["dynamic"], name)
                self.assertNotIn(edge["target"].split(".")[0],
                                 {"urllib", "requests", "fastapi", "pydantic", "sqlite3", "subprocess"}, name)
                if edge["target"].startswith("quantagent_platform"):
                    self.assertIn(edge["target"], {"quantagent_platform.contracts",
                                                  "quantagent_platform.sec_response_contracts"}, name)
            if name == "quantagent_platform.sec_response_contracts":
                self.assertFalse(any(e["target"].startswith("quantagent_platform")
                                     for e in module["imports"]))


if __name__ == "__main__":
    unittest.main()
