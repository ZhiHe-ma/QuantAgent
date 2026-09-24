"""One exact, typed SEC Agent handoff route."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from quantagent_platform.contracts import DataPacket, canonical_json
from quantagent_platform.p5_handoff import (
    HandoffError,
    RoutePolicy,
    create_handoff,
    preflight_route,
    verify_handoff,
)
from quantagent_platform.p5_registry import ApprovedRun, RAW_NAMES
from quantagent_platform.plugins import PluginManifest
from quantagent_platform.runner import RunResult


PARENT_ID = "builtin.sec-evidence-producer-agent"
CHILD_ID = "builtin.sec-evidence-review-agent"
READ_WRITE = ["filesystem:read", "filesystem:write"]


def plan_fixture(kind: str):
    parent = kind == "parent"
    agent_id = PARENT_ID if parent else CHILD_ID
    skill_id = ("builtin.sec-evidence-preparation" if parent
                else "builtin.sec-evidence-independent-review")
    recipe_id = "sec-evidence-producer" if parent else "sec-evidence-review"
    plugin = PluginManifest(
        plugin_id="builtin.sec-approved-run-source" if parent
                  else "builtin.sec-handoff-source",
        version="1.0.0",
        capability="source.sec_approved_run" if parent
                   else "source.sec_agent_handoff",
        input_contracts=(),
        output_contract="quantagent.sec_approved_run.v1" if parent
                        else "quantagent.agent_handoff.v1",
        permissions=frozenset({"filesystem:read"}),
    )
    agent = {
        "manifest_type": "quantagent.agent_manifest.v2",
        "input_contract": "quantagent.sec_approved_run.v1" if parent
                          else "quantagent.agent_handoff.v1",
        "output_contract": "quantagent.sec_evidence_bundle.v1" if parent
                           else "quantagent.report.v1",
        "callable_agents": [{"id": CHILD_ID, "version": "1.0.0"}] if parent else [],
        "limits": {
            "max_steps": 3, "max_tool_calls": 1 if parent else 0,
            "max_wall_seconds": 120,
            "max_cost": {"amount_minor": 0, "currency": "USD"},
        },
        "model_policy": {
            "required_capabilities": {
                "text_generation": False, "structured_output": False,
                "tool_calling": False, "min_context_tokens": 1,
                "offline_replay": False,
            },
            "allowed_models": [],
        },
    }
    entry = lambda ident, digest: SimpleNamespace(
        identifier=ident, version="1.0.0", sha256=digest)
    return SimpleNamespace(
        catalog=SimpleNamespace(sha256="a" * 64),
        agent_entry=entry(agent_id, "b" * 64 if parent else "c" * 64),
        skill_entry=entry(skill_id, "d" * 64 if parent else "e" * 64),
        recipe_entry=entry(recipe_id, "f" * 64 if parent else "0" * 64),
        agent=agent,
        skill={"content": {"package_sha256": "1" * 64 if parent else "2" * 64}},
        resolved_plugins=(({"id": "load-approved-sec-run" if parent
                            else "load-sec-handoff"},
                           SimpleNamespace(manifest=plugin)),),
    )


def route_for(parent, child):
    def snapshot(plan, permissions):
        return {
            "agent": {
                "id": plan.agent_entry.identifier,
                "version": plan.agent_entry.version,
                "manifest_sha256": plan.agent_entry.sha256,
            },
            "skill": {
                "id": plan.skill_entry.identifier,
                "version": plan.skill_entry.version,
                "manifest_sha256": plan.skill_entry.sha256,
                "package_sha256": plan.skill["content"]["package_sha256"],
            },
            "recipe": {
                "id": plan.recipe_entry.identifier,
                "version": plan.recipe_entry.version,
                "sha256": plan.recipe_entry.sha256,
            },
            "plugins": [{
                "step_id": step["id"],
                "plugin_id": plugin.manifest.plugin_id,
                "version": plugin.manifest.version,
                "capability": plugin.manifest.capability,
                "input_contracts": list(plugin.manifest.input_contracts),
                "output_contract": plugin.manifest.output_contract,
                "permissions": sorted(plugin.manifest.permissions),
                "network_access": plugin.manifest.network_access,
            } for step, plugin in plan.resolved_plugins],
            "permissions": permissions,
        }
    return {
        "policy_version": "quantagent.p5_sec_route.v1",
        "task_type": "sec.review_fy2025_mara_riot.v1",
        "source_contract": "quantagent.sec_approved_run.v1",
        "catalog_sha256": parent.catalog.sha256,
        "parent": snapshot(parent, READ_WRITE),
        "child": snapshot(child, READ_WRITE),
        "limits": {
            "max_depth": 1, "max_handoffs": 1, "max_wall_seconds": 120,
            "max_model_cost_minor": 0, "currency": "USD",
        },
    }


class HandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent_plan = plan_fixture("parent")
        self.child_plan = plan_fixture("child")
        self.policy_path = self.root / "policy.json"
        self.policy_data = route_for(self.parent_plan, self.child_plan)
        self.write_policy()

    def write_policy(self) -> None:
        self.policy_path.write_text(
            canonical_json(self.policy_data), encoding="utf-8")
        self.policy = RoutePolicy.load(self.policy_path)

    def make_handoff(self):
        run_dir = self.root / "parent-run"
        run_dir.mkdir(exist_ok=True)
        packet = DataPacket.create(
            contract_version="quantagent.sec_evidence_bundle.v1",
            packet_type="sec_evidence_bundle",
            source="builtin.sec-evidence-preparer",
            records=[{"sample": "fixed"}],
        )
        packet_path = self.root / "broker-bundle.json"
        packet_path.write_text(canonical_json(packet.to_dict()), encoding="utf-8")
        parent = RunResult(
            run_id="parent-run", status="completed", run_dir=run_dir,
            final_packet=packet,
            steps=({"id": "prepare-sec-evidence", "status": "completed",
                    "output_sha256": packet.content_sha256,
                    "packet_path": str(run_dir / "02-prepare-sec-evidence.json")},),
        )
        source = ApprovedRun(
            source_id="synthetic-p4", run_id="source-run",
            run_dir=self.root / "source-run", registry_sha256="3" * 64,
            packet_sha256="4" * 64, report_sha256="5" * 64,
            raw_sha256={name: "6" * 64 for name in RAW_NAMES},
            recipe_id="sec-industry-peers", recipe_version="1.0.0",
            source_plugin_id="builtin.sec-edgar-source",
            source_plugin_version="1.0.0",
        )
        now = datetime.now(timezone.utc)
        handoff = create_handoff(
            self.policy, parent, packet_path, source, "chain-001",
            now, now + timedelta(seconds=120),
        )
        return handoff, now

    def test_exact_route_and_canonical_handoff(self) -> None:
        effective = preflight_route(
            self.policy, self.parent_plan, self.child_plan,
            frozenset(READ_WRITE))
        self.assertEqual(effective, frozenset(READ_WRITE))
        handoff, now = self.make_handoff()
        self.assertLessEqual(len(handoff.raw), 16 * 1024)
        self.assertEqual(handoff.envelope["target"]["id"], CHILD_ID)
        self.assertEqual(handoff.envelope["remaining_handoff_calls"], 1)
        self.assertEqual(handoff.envelope["model_cost_minor"], 0)
        self.assertIsNotNone(
            datetime.fromisoformat(handoff.envelope["expires_at"]).tzinfo)
        self.assertEqual(
            verify_handoff(handoff.raw, handoff.sha256, self.policy, now).sha256,
            handoff.sha256,
        )

    def test_route_rejects_manifest_catalog_plugin_and_permission_drift(self) -> None:
        mutations = (
            lambda: self.parent_plan.agent["callable_agents"].clear(),
            lambda: setattr(self.child_plan.catalog, "sha256", "9" * 64),
            lambda: setattr(self.child_plan.recipe_entry, "sha256", "9" * 64),
            lambda: setattr(
                self.child_plan.resolved_plugins[0][1], "manifest",
                replace(self.child_plan.resolved_plugins[0][1].manifest,
                        version="2.0.0")),
        )
        for change in mutations:
            with self.subTest(change=change):
                parent, child = plan_fixture("parent"), plan_fixture("child")
                self.parent_plan, self.child_plan = parent, child
                change()
                with self.assertRaises(HandoffError):
                    preflight_route(
                        self.policy, parent, child, frozenset(READ_WRITE))
        with self.assertRaises(HandoffError):
            preflight_route(
                self.policy, plan_fixture("parent"), plan_fixture("child"),
                frozenset({"filesystem:read"}))

    def test_route_rejects_contract_permission_network_and_cycle(self) -> None:
        cases = (
            lambda parent, child: parent.agent.update(
                input_contract="quantagent.unapproved_source.v1"),
            lambda parent, child: parent.agent.update(
                model_policy={**parent.agent["model_policy"],
                              "allowed_models": ["unexpected-model"]}),
            lambda parent, child: setattr(
                child.resolved_plugins[0][1], "manifest",
                replace(child.resolved_plugins[0][1].manifest,
                        output_contract="quantagent.other.v1")),
            lambda parent, child: setattr(
                child.resolved_plugins[0][1], "manifest",
                replace(child.resolved_plugins[0][1].manifest,
                        permissions=frozenset({"network:read"}))),
            lambda parent, child: setattr(
                child.resolved_plugins[0][1], "manifest",
                replace(child.resolved_plugins[0][1].manifest,
                        network_access=True)),
            lambda parent, child: setattr(
                child.agent_entry, "identifier", PARENT_ID),
        )
        for mutate in cases:
            with self.subTest(mutate=mutate):
                parent, child = plan_fixture("parent"), plan_fixture("child")
                mutate(parent, child)
                with self.assertRaises(HandoffError):
                    preflight_route(
                        self.policy, parent, child, frozenset(READ_WRITE))

    def test_policy_rejects_target_task_and_plugin_changes(self) -> None:
        for field, replacement in (
            ("task_type", "sec.unexpected.v1"),
            ("source_contract", "quantagent.unapproved_source.v1"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.policy_data)
                changed[field] = replacement
                self.policy_path.write_text(canonical_json(changed), encoding="utf-8")
                with self.assertRaises(HandoffError):
                    RoutePolicy.load(self.policy_path)
        changed = copy.deepcopy(self.policy_data)
        changed["child"]["agent"]["id"] = PARENT_ID
        self.policy_path.write_text(canonical_json(changed), encoding="utf-8")
        with self.assertRaises(HandoffError):
            RoutePolicy.load(self.policy_path)
        changed = copy.deepcopy(self.policy_data)
        changed["child"]["plugins"][0]["network_access"] = True
        self.policy_path.write_text(canonical_json(changed), encoding="utf-8")
        with self.assertRaises(HandoffError):
            RoutePolicy.load(self.policy_path)

    def test_handoff_rejects_tampering_expiry_target_and_depth(self) -> None:
        handoff, now = self.make_handoff()
        for field, value in (
            ("task_type", "sec.other.v1"),
            ("depth", 2),
            ("remaining_handoff_calls", 2),
            ("idempotency_key", "other-chain"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(handoff.envelope)
                changed[field] = value
                raw = canonical_json(changed).encode()
                with self.assertRaises(HandoffError):
                    verify_handoff(raw, handoff.sha256, self.policy, now)
        changed = copy.deepcopy(handoff.envelope)
        changed["target"]["version"] = "2.0.0"
        raw = canonical_json(changed).encode()
        with self.assertRaises(HandoffError):
            verify_handoff(raw, hashlib.sha256(raw).hexdigest(), self.policy, now)
        for mutate in (
            lambda row: row["source_pins"].update(packet_sha256="9" * 64),
            lambda row: row["bundle"].update(file_sha256="8" * 64),
            lambda row: row.update(effective_permissions=["filesystem:read"]),
        ):
            with self.subTest(mutate=mutate):
                changed = copy.deepcopy(handoff.envelope)
                mutate(changed)
                raw = canonical_json(changed).encode()
                with self.assertRaises(HandoffError):
                    verify_handoff(raw, handoff.sha256, self.policy, now)
        expiry = datetime.fromisoformat(handoff.envelope["expires_at"])
        with self.assertRaises(HandoffError):
            verify_handoff(handoff.raw, handoff.sha256, self.policy, expiry)


if __name__ == "__main__":
    unittest.main()
