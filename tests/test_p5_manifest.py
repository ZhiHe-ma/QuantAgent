"""AgentManifest v2 admission without changing the v1 contract."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from quantagent_platform.manifests import ManifestError, load_agent_manifest


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "agent_catalog" / "agents" / "data-health-agent" / "agent.yaml"
CHILD = {"id": "builtin.sec-evidence-review-agent", "version": "1.0.0"}


class AgentManifestV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sample = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))

    def _write(self, name: str, *, version: str, children: list[dict[str, str]]) -> Path:
        value = dict(self.sample)
        value["manifest_type"] = version
        value["callable_agents"] = children
        path = self.root / name
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
        return path

    def test_v2_allows_one_exact_child_reference(self) -> None:
        path = self._write(
            "v2.yaml",
            version="quantagent.agent_manifest.v2",
            children=[CHILD],
        )
        loaded = load_agent_manifest(path)
        self.assertEqual(loaded.data["manifest_type"], "quantagent.agent_manifest.v2")
        self.assertEqual(loaded.data["callable_agents"], [CHILD])

    def test_v1_still_rejects_a_child_reference(self) -> None:
        path = self._write(
            "v1-child.yaml",
            version="quantagent.agent_manifest.v1",
            children=[CHILD],
        )
        with self.assertRaises(ManifestError):
            load_agent_manifest(path)

    def test_v2_rejects_two_child_references(self) -> None:
        path = self._write(
            "v2-two.yaml",
            version="quantagent.agent_manifest.v2",
            children=[CHILD, {"id": "builtin.other-agent", "version": "1.0.0"}],
        )
        with self.assertRaises(ManifestError):
            load_agent_manifest(path)

    def test_unknown_manifest_type_fails_closed(self) -> None:
        path = self._write(
            "v3.yaml",
            version="quantagent.agent_manifest.v3",
            children=[],
        )
        with self.assertRaises(ManifestError):
            load_agent_manifest(path)


if __name__ == "__main__":
    unittest.main()
