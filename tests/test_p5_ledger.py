"""Persistent, atomic P5 chain reservation and audit transitions."""

from __future__ import annotations

import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from quantagent_platform.p5_ledger import (
    HandoffLedger, IdempotencyConflict, LedgerError,
)


FINGERPRINT = "a" * 64


def reserve_in_process(root: str) -> tuple[str, bool]:
    return HandoffLedger(Path(root)).reserve("operator-001", FINGERPRINT)


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = HandoffLedger(self.root)

    def test_same_request_reuses_chain_and_conflict_fails(self) -> None:
        first = self.ledger.reserve("operator-001", FINGERPRINT)
        second = self.ledger.reserve("operator-001", FINGERPRINT)
        self.assertEqual(first[0], second[0])
        self.assertTrue(first[1])
        self.assertFalse(second[1])
        self.assertEqual(self.ledger.get_by_request("operator-001")["chain_id"], first[0])
        with self.assertRaises(IdempotencyConflict):
            self.ledger.reserve("operator-001", "b" * 64)

    def test_concurrent_processes_create_one_chain(self) -> None:
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve_in_process, [str(self.root)] * 8))
        self.assertEqual(len({chain_id for chain_id, _ in results}), 1)
        self.assertEqual(sum(created for _, created in results), 1)
        record = self.ledger.get(results[0][0])
        self.assertEqual(len(record["events"]), 1)

    def test_ordered_events_and_terminal_state(self) -> None:
        chain_id, _ = self.ledger.reserve("operator-002", FINGERPRINT)
        self.ledger.transition(chain_id, "parent_running", parent_id="parent-run")
        self.ledger.transition(chain_id, "parent_completed", bundle_sha256="b" * 64)
        self.ledger.transition(chain_id, "handoff_ready", handoff_sha256="c" * 64,
                               handoff_calls=1)
        self.ledger.transition(chain_id, "child_running", child_id="child-run")
        self.ledger.transition(chain_id, "completed", wall_ms=98)
        record = self.ledger.get(chain_id)
        self.assertEqual([event["seq"] for event in record["events"]],
                         [1, 2, 3, 4, 5, 6])
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["child_id"], "child-run")
        with self.assertRaises(LedgerError):
            self.ledger.transition(chain_id, "completed")
        with self.assertRaises(LedgerError):
            self.ledger.transition(chain_id, "failed", failure_code="child_failed")

        failed_id, _ = self.ledger.reserve("operator-failed", "b" * 64)
        self.ledger.transition(failed_id, "failed", failure_code="admission_rejected")
        with self.assertRaises(LedgerError):
            self.ledger.transition(failed_id, "completed")

    def test_restart_marks_running_chain_interrupted_without_child(self) -> None:
        chain_id, _ = self.ledger.reserve("operator-003", FINGERPRINT)
        self.ledger.transition(chain_id, "parent_running", parent_id="parent-run")
        reopened = HandoffLedger(self.root)
        self.assertEqual(reopened.recover_interrupted(), 1)
        record = reopened.get(chain_id)
        self.assertEqual(record["status"], "interrupted")
        self.assertIsNone(record["child_id"])
        self.assertEqual(record["events"][-1]["status"], "interrupted")
        self.assertEqual(reopened.recover_interrupted(), 0)

    def test_opening_existing_v1_ledger_does_not_rewrite_database(self) -> None:
        chain_id, _ = self.ledger.reserve("operator-readonly", FINGERPRINT)
        before = self.ledger.path.stat().st_mtime_ns
        reopened = HandoffLedger(self.root)
        self.assertEqual(reopened.get(chain_id)["status"], "admitted")
        self.assertEqual(self.ledger.path.stat().st_mtime_ns, before)

    def test_invalid_fields_and_illegal_jump_leave_audit_unchanged(self) -> None:
        chain_id, _ = self.ledger.reserve("operator-004", FINGERPRINT)
        for fields in (
            {"private_path": "C:/secret"},
            {"failure_code": "C:/secret"},
            {"permissions_json": ["network:https"]},
            {"source_packet_sha256": "wrong"},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(LedgerError):
                    self.ledger.transition(chain_id, "parent_running", **fields)
        with self.assertRaises(LedgerError):
            self.ledger.transition(chain_id, "child_running", child_id="child-run")
        self.assertEqual(len(self.ledger.get(chain_id)["events"]), 1)


if __name__ == "__main__":
    unittest.main()
