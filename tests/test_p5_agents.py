"""Curated P5 Agent chain over a synthetic, approved P4 SEC run."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from quantagent_platform.agents import AgentRuntime
from quantagent_platform.contracts import DataPacket, canonical_json
from quantagent_platform.p5_handoff import RoutePolicy, create_handoff, preflight_route
from quantagent_platform.p5_registry import ApprovedRunRegistry, RAW_NAMES
from quantagent_platform.runner import RecipeRunner, default_registry
from tests.test_sec_contracts import make_responses


ROOT = Path(__file__).resolve().parents[1]
PARENT = "builtin.sec-evidence-producer-agent"
CHILD = "builtin.sec-evidence-review-agent"


class P5AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def runtime(self) -> AgentRuntime:
        return AgentRuntime(runner=RecipeRunner(default_registry()))

    def approved_source(self):
        runs = self.root / "p4-runs"
        recipe = RecipeRunner.load_recipe(ROOT / "recipes" / "sec_industry_peers.json")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=make_responses()):
                result = RecipeRunner(default_registry()).run(
                    recipe, params={"source_path": "", "report_title": "Synthetic SEC sample"},
                    output_dir=runs, allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False, run_id="synthetic-p4-run",
                )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        entry = {
            "approved_source_id": "synthetic-p4", "run_id": result.run_id,
            "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
            "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
            "packet_sha256": digest(result.run_dir / "01-load-sec-facts.json"),
            "report_sha256": digest(result.run_dir / "sec_industry_peers.md"),
            "raw_sha256": {name: digest(result.run_dir / name) for name in RAW_NAMES},
        }
        registry = self.root / "approved.json"
        registry.write_text(canonical_json({
            "registry_version": "quantagent.sec_approved_run.v1", "entries": [entry],
        }), encoding="utf-8")
        source = ApprovedRunRegistry.load(registry, runs).resolve("synthetic-p4")
        return registry, runs, source

    def test_exact_agents_and_route_policy_resolve(self) -> None:
        runtime = self.runtime()
        parent = runtime.resolve(agent_id=PARENT, agent_version="1.0.0", offline=True)
        child = runtime.resolve(agent_id=CHILD, agent_version="1.0.0", offline=True)
        self.assertEqual(parent.agent["callable_agents"],
                         [{"id": CHILD, "version": "1.0.0"}])
        self.assertEqual(child.agent["callable_agents"], [])
        self.assertTrue(parent.agent["metadata"]["coordinator_only"])
        self.assertTrue(child.agent["metadata"]["coordinator_only"])
        self.assertEqual([step[0]["id"] for step in parent.resolved_plugins], [
            "load-approved-sec-run", "prepare-sec-evidence"])
        self.assertEqual([step[0]["id"] for step in child.resolved_plugins], [
            "load-sec-handoff", "review-sec-evidence", "write-sec-review"])
        policy = RoutePolicy.load(ROOT / "policies" / "p5_sec_route.v1.json")
        self.assertEqual(preflight_route(policy, parent, child,
                                        frozenset({"filesystem:read", "filesystem:write"})),
                         frozenset({"filesystem:read", "filesystem:write"}))
        self.assertTrue(all(not plugin.manifest.network_access for _, plugin
                            in (*parent.resolved_plugins, *child.resolved_plugins)))

    def test_synthetic_parent_child_runs_linked_report(self) -> None:
        registry, runs, source = self.approved_source()
        runtime = self.runtime()
        parent = runtime.run(
            agent_id=PARENT, agent_version="1.0.0",
            params={"registry_path": str(registry), "approved_run_root": str(runs),
                    "approved_source_id": source.source_id},
            output_dir=self.root / "parent", allowed_read_roots=[self.root],
            allowed_write_roots=[self.root], run_id="parent-run",
        )
        self.assertEqual(parent.final_packet.contract_version,
                         "quantagent.sec_evidence_bundle.v1")
        self.assertEqual(len(parent.final_packet.records), 1)
        policy = RoutePolicy.load(ROOT / "policies" / "p5_sec_route.v1.json")
        now = datetime.now(timezone.utc)
        handoff = create_handoff(
            policy, parent, parent.run_dir / "02-prepare-sec-evidence.json",
            source, "chain-001", now, now + timedelta(seconds=120),
        )
        broker = self.root / "broker"
        broker.mkdir()
        handoff_path = broker / "handoff.json"
        handoff_path.write_bytes(handoff.raw)
        child = runtime.run(
            agent_id=CHILD, agent_version="1.0.0",
            params={"handoff_path": str(handoff_path),
                    "handoff_sha256": handoff.sha256,
                    "policy_path": str(ROOT / "policies" / "p5_sec_route.v1.json"),
                    "bundle_path": str(parent.run_dir / "02-prepare-sec-evidence.json"),
                    "approved_run_root": str(runs)},
            output_dir=self.root / "child",
            allowed_read_roots=[self.root, ROOT],
            allowed_write_roots=[self.root], run_id="child-run",
        )
        self.assertEqual(child.final_packet.contract_version, "quantagent.report.v1")
        report = child.final_packet.records[0]
        self.assertEqual(report["format"], "markdown")
        self.assertEqual(report["input_sha256"],
                         DataPacket.from_dict(json.loads(
                             (child.run_dir / "02-review-sec-evidence.json").read_text(
                                 encoding="utf-8"))).content_sha256)
        self.assertEqual(report["artifact_sha256"], hashlib.sha256(
            Path(report["path"]).read_bytes()).hexdigest())
        self.assertIn("Independent SEC evidence review",
                      Path(report["path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
