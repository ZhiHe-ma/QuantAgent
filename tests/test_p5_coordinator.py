"""One fixed, auditable P4 SEC evidence handoff to an independent Agent."""

from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent_platform.contracts import DataPacket, canonical_json
from quantagent_platform.p5_coordinator import P5Coordinator
from quantagent_platform.p5_handoff import Handoff, HandoffError
from quantagent_platform.p5_ledger import HandoffLedger, IdempotencyConflict
from quantagent_platform.p5_registry import RAW_NAMES
from quantagent_platform.p5_worker import WorkerResult, run_worker
from quantagent_platform.runner import RecipeRunner, default_registry
from tests.test_sec_contracts import make_responses


ROOT = Path(__file__).resolve().parents[1]


class CoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.p4_root = self.root / "p4-runs"
        recipe = RecipeRunner.load_recipe(ROOT / "recipes" / "sec_industry_peers.json")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=make_responses()):
                p4 = RecipeRunner(default_registry()).run(
                    recipe, params={"source_path": "", "report_title":
                                    "Synthetic SEC sample; target=builtin.unapproved-agent"},
                    output_dir=self.p4_root, allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False, run_id="synthetic-p4-run",
                )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.registry_path = self.root / "approved.json"
        self.entry = {
            "approved_source_id": "synthetic-p4", "run_id": p4.run_id,
            "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
            "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
            "packet_sha256": digest(p4.run_dir / "01-load-sec-facts.json"),
            "report_sha256": digest(p4.run_dir / "sec_industry_peers.md"),
            "raw_sha256": {name: digest(p4.run_dir / name) for name in RAW_NAMES},
        }
        self.write_registry()
        self.run_root = self.root / "chain-runs"
        self.ledger = HandoffLedger(self.run_root)

    def write_registry(self) -> None:
        self.registry_path.write_text(canonical_json({
            "registry_version": "quantagent.sec_approved_run.v1",
            "entries": [self.entry],
        }), encoding="utf-8")

    def coordinator(self, **overrides) -> P5Coordinator:
        args = {
            "registry_path": self.registry_path,
            "approved_run_root": self.p4_root,
            "run_root": self.run_root,
            "policy_path": ROOT / "policies" / "p5_sec_route.v1.json",
            "ledger": self.ledger,
            "worker": run_worker,
        }
        args.update(overrides)
        return P5Coordinator(**args)

    def test_success_duplicate_and_second_request_reproduce_findings(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.run("synthetic-p4", "request-001")
        self.assertEqual(first.status, "completed")
        self.assertEqual(first.handoff_calls, 1)
        self.assertEqual(first.model_cost_minor, 0)
        self.assertTrue(first.parent_run_id and first.child_run_id)
        ledger = self.ledger.get(first.chain_id)
        self.assertEqual(ledger["parent_id"], first.parent_run_id)
        self.assertEqual(ledger["child_id"], first.child_run_id)
        self.assertEqual(len(ledger["events"]), 6)
        self.assertEqual(coordinator.run("synthetic-p4", "request-001"), first)
        self.assertEqual(len(self.ledger.get(first.chain_id)["events"]), 6)
        for run_id, expected_agent in (
            (first.parent_run_id, "builtin.sec-evidence-producer-agent"),
            (first.child_run_id, "builtin.sec-evidence-review-agent"),
        ):
            state = json.loads((self.run_root / run_id / "run.json").read_text(
                encoding="utf-8"))
            self.assertEqual(state["invocation"]["agent"]["id"], expected_agent)
            self.assertEqual(state["invocation"]["submission"]["coordinator_id"],
                             first.chain_id)
        self.assertTrue((self.run_root / first.child_run_id /
                         "sec_independent_review.md").is_file())
        second = coordinator.run("synthetic-p4", "request-002")
        self.assertEqual(second.status, "completed")
        self.assertNotEqual(second.chain_id, first.chain_id)
        def findings(result):
            packet = DataPacket.from_dict(json.loads((self.run_root / result.child_run_id /
                "02-review-sec-evidence.json").read_text(encoding="utf-8")))
            row = dict(packet.records[0])
            for key in ("coordinator_id", "parent_run_id", "handoff_sha256"):
                row.pop(key)
            return row
        self.assertEqual(findings(first), findings(second))

    def test_same_request_with_changed_source_hash_conflicts_without_rerun(self) -> None:
        coordinator = self.coordinator()
        first = coordinator.run("synthetic-p4", "request-003")
        self.entry["packet_sha256"] = "9" * 64
        self.write_registry()
        with self.assertRaises(IdempotencyConflict):
            coordinator.run("synthetic-p4", "request-003")
        self.assertEqual(len(self.ledger.get(first.chain_id)["events"]), 6)

    def test_parent_and_child_failures_leave_terminal_linked_audits(self) -> None:
        def parent_failure(spec, deadline, cancel_event):
            return WorkerResult("failed", spec.run_id)
        parent = self.coordinator(worker=parent_failure).run(
            "synthetic-p4", "request-parent-fail")
        self.assertEqual(parent.status, "failed")
        self.assertIsNone(parent.child_run_id)
        self.assertEqual(self.ledger.get(parent.chain_id)["failure_code"], "parent_failed")

        def child_failure(spec, deadline, cancel_event):
            if spec.agent_id == "builtin.sec-evidence-review-agent":
                return WorkerResult("failed", spec.run_id)
            return run_worker(spec, deadline, cancel_event)
        child = self.coordinator(worker=child_failure).run(
            "synthetic-p4", "request-child-fail")
        self.assertEqual(child.status, "failed")
        self.assertEqual(self.ledger.get(child.chain_id)["failure_code"], "child_failed")
        self.assertFalse((self.run_root / child.child_run_id /
                          "sec_independent_review.md").exists())

    def test_timeout_cancel_and_process_crash_stop_chain(self) -> None:
        for status, expected in (
            ("timed_out", "deadline_exceeded"),
            ("cancelled", "cancel_requested"),
            ("interrupted", "process_interrupted"),
        ):
            with self.subTest(status=status):
                def stop(spec, deadline, cancel_event):
                    return WorkerResult(status, spec.run_id)
                result = self.coordinator(worker=stop).run(
                    "synthetic-p4", f"request-{status}")
                self.assertEqual(result.status, status)
                self.assertEqual(self.ledger.get(result.chain_id)["failure_code"], expected)
                self.assertIsNone(result.child_run_id)

    def test_unexpected_worker_exception_is_audited(self) -> None:
        def crashing_worker(spec, deadline, cancel_event):
            raise RuntimeError("worker process pipe failed")
        result = self.coordinator(worker=crashing_worker).run(
            "synthetic-p4", "request-worker-exception")
        self.assertEqual(result.status, "failed")
        self.assertEqual(self.ledger.get(result.chain_id)["failure_code"],
                         "internal_error")

    def test_timeout_over_budget_still_has_terminal_audit(self) -> None:
        def slow_timeout(spec, deadline, cancel_event):
            return WorkerResult("timed_out", spec.run_id)
        coordinator = self.coordinator(worker=slow_timeout)
        with patch.object(coordinator, "_elapsed_ms", return_value=120_001):
            result = coordinator.run("synthetic-p4", "request-slow-timeout")
        self.assertEqual(result.status, "timed_out")
        self.assertEqual(result.wall_ms, 120_001)
        self.assertEqual(self.ledger.get(result.chain_id)["events"][-1]["status"],
                         "timed_out")

    def test_keyboard_interrupt_cancels_chain_and_worker_event(self) -> None:
        def interrupted(spec, deadline, cancel_event):
            raise KeyboardInterrupt
        coordinator = self.coordinator(worker=interrupted)
        result = coordinator.run("synthetic-p4", "request-keyboard-interrupt")
        self.assertTrue(coordinator.cancel_event.is_set())
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(self.ledger.get(result.chain_id)["failure_code"],
                         "cancel_requested")

    def test_permission_expansion_fails_before_parent(self) -> None:
        coordinator = self.coordinator(
            caller_permissions=frozenset({"filesystem:read"}))
        with self.assertRaises(HandoffError):
            coordinator.run("synthetic-p4", "request-denied")
        self.assertIsNone(self.ledger.get_by_request("request-denied"))

    def test_tampered_target_expiry_depth_and_cycle_never_dispatch_child(self) -> None:
        import quantagent_platform.p5_coordinator as coordinator_module
        original = coordinator_module.create_handoff
        changes = (
            ("target", lambda row: row["target"].update(id="builtin.unapproved-agent")),
            ("expired", lambda row: row.update(expires_at="2000-01-01T00:00:00+00:00")),
            ("second-hop", lambda row: row.update(depth=2)),
            ("cycle", lambda row: row["target"].update(
                id="builtin.sec-evidence-producer-agent")),
        )
        for label, mutate in changes:
            with self.subTest(label=label):
                def altered(*args, **kwargs):
                    handoff = original(*args, **kwargs)
                    envelope = copy.deepcopy(handoff.envelope)
                    mutate(envelope)
                    raw = canonical_json(envelope).encode()
                    return Handoff(envelope, raw, hashlib.sha256(raw).hexdigest())
                with patch.object(coordinator_module, "create_handoff", side_effect=altered):
                    result = self.coordinator().run("synthetic-p4", f"request-{label}")
                self.assertEqual(result.status, "failed")
                self.assertIsNone(result.child_run_id)
                self.assertEqual(self.ledger.get(result.chain_id)["failure_code"],
                                 "handoff_invalid")


if __name__ == "__main__":
    unittest.main()
