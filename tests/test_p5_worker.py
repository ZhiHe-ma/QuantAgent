"""Spawn-safe bounded supervision of one deterministic Agent execution."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent_platform.contracts import DataPacket, canonical_json
from quantagent_platform.p5_worker import WorkerSpec, WorkerSupervisor, run_worker
from quantagent_platform.p5_registry import RAW_NAMES
from quantagent_platform.runner import RecipeRunner, default_registry
from tests.test_sec_contracts import make_responses


def fixture_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    spec = json.loads(spec_raw)
    run_dir = Path(spec["output_root"]) / spec["run_id"]
    run_dir.mkdir(parents=True)
    packet = DataPacket.create(
        contract_version="quantagent.sec_evidence_bundle.v1",
        packet_type="sec_evidence_bundle", source="builtin.sec-evidence-preparer",
        records=[{"sample": "fixed"}],
    )
    path = run_dir / "02-prepare-sec-evidence.json"
    raw = canonical_json(packet.to_dict()).encode()
    path.write_bytes(raw)
    connection.send_bytes(canonical_json({
        "status": "completed", "run_id": spec["run_id"], "packet_path": str(path),
        "packet_sha256": hashlib.sha256(raw).hexdigest(),
        "content_sha256": packet.content_sha256,
    }).encode())


def sleeping_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    time.sleep(10)


def cancel_aware_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    spec = json.loads(spec_raw)
    Path(spec["output_root"]).mkdir(parents=True, exist_ok=True)
    (Path(spec["output_root"]) / "worker-started").write_text("ready")
    while not cancel_flag.is_set():
        time.sleep(0.02)
    connection.send_bytes(canonical_json({
        "status": "cancelled", "run_id": spec["run_id"],
    }).encode())


def abrupt_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    spec = json.loads(spec_raw)
    run_dir = Path(spec["output_root"]) / spec["run_id"]
    run_dir.mkdir(parents=True)
    (run_dir / "02-prepare-sec-evidence.json").write_bytes(b"partial")
    raise SystemExit(7)


def malformed_result_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    spec = json.loads(spec_raw)
    connection.send_bytes(canonical_json({
        "status": "completed", "run_id": spec["run_id"],
        "packet_path": None, "packet_sha256": "a" * 64,
        "content_sha256": "b" * 64,
    }).encode())


class WorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def spec(self, run_id: str = "worker-run") -> WorkerSpec:
        return WorkerSpec(
            agent_id="builtin.sec-evidence-producer-agent", agent_version="1.0.0",
            skill_id="builtin.sec-evidence-preparation", skill_version="1.0.0",
            recipe_id="sec-evidence-producer", recipe_version="1.0.0",
            params={"registry_path": str(self.root / "approved.json"),
                    "approved_run_root": str(self.root / "p4-runs"),
                    "approved_source_id": "synthetic-p4"},
            run_id=run_id, output_root=str(self.root / "output"),
            read_roots=[str(self.root)], write_roots=[str(self.root)],
            permissions=["filesystem:read", "filesystem:write"],
            submission_context={"coordinator_id": "chain-001"},
        )

    def test_spawned_success_checks_returned_packet(self) -> None:
        outcome = WorkerSupervisor(_test_entrypoint=fixture_worker).run(
            self.spec(), deadline=time.monotonic() + 3, cancel_event=multiprocessing.Event())
        self.assertEqual(outcome.status, "completed")
        self.assertTrue(outcome.packet_path.is_file())
        self.assertEqual(outcome.run_id, "worker-run")
        self.assertEqual(outcome.packet_sha256,
                         hashlib.sha256(outcome.packet_path.read_bytes()).hexdigest())

    def test_deadline_terminates_blocked_worker(self) -> None:
        started = time.monotonic()
        outcome = WorkerSupervisor(_test_entrypoint=sleeping_worker).run(
            self.spec(), deadline=started + 0.4, cancel_event=multiprocessing.Event())
        self.assertEqual(outcome.status, "timed_out")
        self.assertIsNone(outcome.packet_path)
        self.assertLess(time.monotonic() - started, 6)
        self.assertFalse((self.root / "output" / "worker-run" /
                          "03-write-sec-review.json").exists())

    def test_cancel_during_worker_returns_cancelled(self) -> None:
        cancel = multiprocessing.Event()
        marker = self.root / "output" / "worker-started"
        def cancel_after_start() -> None:
            until = time.monotonic() + 2
            while not marker.exists() and time.monotonic() < until:
                time.sleep(0.01)
            if marker.exists():
                cancel.set()
        trigger = threading.Thread(target=cancel_after_start)
        trigger.start()
        try:
            outcome = WorkerSupervisor(_test_entrypoint=cancel_aware_worker).run(
                self.spec(), deadline=time.monotonic() + 3, cancel_event=cancel)
        finally:
            trigger.join(timeout=3)
        self.assertTrue(marker.exists())
        self.assertEqual(outcome.status, "cancelled")
        self.assertIsNone(outcome.packet_path)

    def test_abrupt_exit_after_packet_is_interrupted(self) -> None:
        outcome = WorkerSupervisor(_test_entrypoint=abrupt_worker).run(
            self.spec(), deadline=time.monotonic() + 3,
            cancel_event=multiprocessing.Event())
        self.assertEqual(outcome.status, "interrupted")
        self.assertIsNone(outcome.packet_path)
        self.assertFalse((self.root / "output" / "worker-run" /
                          "03-write-sec-review.json").exists())

    def test_malformed_success_result_is_interrupted(self) -> None:
        outcome = WorkerSupervisor(_test_entrypoint=malformed_result_worker).run(
            self.spec(), deadline=time.monotonic() + 3,
            cancel_event=multiprocessing.Event())
        self.assertEqual(outcome.status, "interrupted")

    def test_spec_rejects_unapproved_agent_and_object_params(self) -> None:
        with self.assertRaises(ValueError):
            WorkerSpec(**{**self.spec().__dict__, "agent_id": "unknown"})
        with self.assertRaises(ValueError):
            WorkerSpec(**{**self.spec().__dict__, "params": {"bad": object()}})
        self.assertTrue(callable(run_worker))

    def test_production_entrypoint_runs_approved_parent_in_spawn(self) -> None:
        root = self.root / "p4-runs"
        repository = Path(__file__).resolve().parents[1]
        recipe = RecipeRunner.load_recipe(repository / "recipes" / "sec_industry_peers.json")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=make_responses()):
                p4 = RecipeRunner(default_registry()).run(
                    recipe, params={"source_path": "", "report_title": "Synthetic SEC sample"},
                    output_dir=root, allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False, run_id="synthetic-p4-run",
                )
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        registry_path = self.root / "approved.json"
        registry_path.write_text(canonical_json({
            "registry_version": "quantagent.sec_approved_run.v1",
            "entries": [{
                "approved_source_id": "synthetic-p4", "run_id": p4.run_id,
                "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
                "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
                "packet_sha256": digest(p4.run_dir / "01-load-sec-facts.json"),
                "report_sha256": digest(p4.run_dir / "sec_industry_peers.md"),
                "raw_sha256": {name: digest(p4.run_dir / name) for name in RAW_NAMES},
            }],
        }), encoding="utf-8")
        result = run_worker(self.spec(), time.monotonic() + 10,
                            multiprocessing.Event())
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.packet_path.name, "02-prepare-sec-evidence.json")
        self.assertEqual(DataPacket.from_dict(json.loads(
            result.packet_path.read_text(encoding="utf-8"))).contract_version,
            "quantagent.sec_evidence_bundle.v1")


if __name__ == "__main__":
    unittest.main()
