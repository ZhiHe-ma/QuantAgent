"""Real file and SQLite owner interfaces; external sends alone are replaced."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.support.recovery_fixtures import daily_payload, isolated_engine
from quantagent_platform.recovery.rules import freeze_snapshot, freeze_audit_payload


class RecoveryPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.ctx = isolated_engine(Path(self.temp.name))
        self.module, self.engine = self.ctx.__enter__()
        self.addCleanup(self.ctx.__exit__, None, None, None)
        self.assertTrue(callable(getattr(self.engine, "project_daily_report", None)), "missing owned recovery projections")

    def snapshot(self, payload=None):
        payload = payload or daily_payload()
        return freeze_snapshot(instance_id=self.engine.recovery_store.instance_id, run_id="run_fixture", kind="daily",
                               date=payload["capsule"]["date"], created_at=payload["started_at"], payload=payload)

    def test_unicode_projection_hash_matches_written_bytes(self):
        snapshot = self.snapshot()
        self.assertEqual(self.engine.project_daily_report(snapshot).status, "succeeded")
        report = Path(self.engine.daily_dir) / (snapshot.date + ".md")
        self.assertEqual(report.read_bytes(), daily_payload()["report"].encode("utf-8"))
        self.assertEqual(self.engine.project_daily_memory(snapshot).status, "succeeded")
        expected = json.dumps(json.loads(snapshot.payload_json)["memory_target"], ensure_ascii=False, indent=2).encode("utf-8")
        self.assertEqual(Path(self.engine.memory_file).read_bytes(), expected)
        self.assertEqual(hashlib.sha256(expected).hexdigest(), self.engine.capture_daily_inputs(snapshot.date)["memory_preimage"])
        with patch.object(self.module.os, "replace", side_effect=AssertionError("duplicate replace")):
            self.assertEqual(self.engine.project_daily_report(snapshot).status, "succeeded")
            self.assertEqual(self.engine.project_daily_memory(snapshot).status, "succeeded")

    def test_projection_conflict_and_replace_failure_preserve_bytes(self):
        path = Path(self.engine.daily_dir) / "2026-10-03.md"
        path.write_bytes(b"manual")
        self.assertEqual(self.engine.project_daily_report(self.snapshot()).status, "needs_review")
        self.assertEqual(path.read_bytes(), b"manual")
        payload = daily_payload();payload["report_preimage"] = hashlib.sha256(b"manual").hexdigest()
        with patch.object(self.module.os, "replace", side_effect=OSError("fixture disk failure")):
            self.assertEqual(self.engine.project_daily_report(self.snapshot(payload)).status, "failed")
        self.assertEqual(path.read_bytes(), b"manual")
        self.assertFalse(list(path.parent.glob("*.tmp")))
        Path(self.engine.memory_file).write_bytes(b"{broken")
        self.assertEqual(self.engine.project_daily_memory(self.snapshot()).status, "needs_review")
        self.assertEqual(Path(self.engine.memory_file).read_bytes(), b"{broken")

    def test_old_memory_is_superseded_without_rolling_duplicate(self):
        new = daily_payload("2026-10-04")["memory_target"]
        Path(self.engine.memory_file).write_text(json.dumps(new), encoding="utf-8")
        before = Path(self.engine.memory_file).read_bytes()
        self.assertEqual(self.engine.project_daily_memory(self.snapshot()).status, "superseded")
        self.assertEqual(Path(self.engine.memory_file).read_bytes(), before)
        Path(self.engine.memory_file).unlink()
        for _ in range(2):
            self.assertEqual(self.engine.project_daily_memory(self.snapshot()).status, "succeeded")
        self.assertEqual(json.loads(Path(self.engine.memory_file).read_text(encoding="utf-8"))["rolling_7d"], [])

    def test_native_and_legacy_delivery_truth(self):
        for body, expected in [({"errcode": 0}, "confirmed"), ({"errcode": 400}, "failed"), ({"errcode": False}, "unknown"), ([], "unknown")]:
            with self.subTest(body=body):
                self.module.requests.post = Mock(return_value=Mock(status_code=200, json=lambda: body))
                self.assertEqual(self.engine.send_wecom_result("fixture").status, expected)
                self.module.requests.post.assert_called_once()
        self.module.requests.post = Mock(side_effect=TimeoutError())
        self.assertEqual(self.engine.send_wecom_result("fixture").status, "unknown")
        self.engine.push_to_wecom = Mock(return_value=False)
        self.assertEqual(self.engine.daily_ports().send_message("fixture").status, "unknown")
        self.engine.push_to_wecom.return_value = True
        self.assertEqual(self.engine.daily_ports().send_message("fixture").status, "confirmed")
        self.engine.wecom_url = None
        self.assertEqual(self.engine.send_wecom_result("fixture").status, "not_configured")

    def test_audit_preflight_idempotency_and_canonical_guard(self):
        store = self.engine.signal_audit_store
        self.assertTrue(callable(getattr(store, "validate_completed_signal", None)))
        with self.assertRaises(Exception):
            store.validate_completed_signal({}, {}, [])
        self.assertFalse(Path(self.engine.signal_audit_file).exists())
        snapshot = self.snapshot()
        payload = freeze_audit_payload(snapshot, {"report": "succeeded", "memory": "succeeded", "message": "unknown"}, snapshot.created_at)
        first = self.engine.commit_frozen_audit(payload)
        self.assertEqual(first["status"], "recorded")
        newer = daily_payload()["audit_facts"]
        newer["run"]["run_id"] = "run_new";newer["signal"]["signal_id"] = "signal_new"
        store.record_completed_signal(**newer)
        for _ in range(2):
            self.assertEqual(self.engine.commit_frozen_audit(payload)["status"], "exists")
        old = daily_payload()["audit_facts"]
        old["run"]["run_id"] = "run_backfill";old["signal"]["signal_id"] = "signal_backfill"
        store.record_recovered_signal(**old, expected_canonical_signal_id="signal_fixture")
        self.assertEqual(store.get_canonical_signal(snapshot.date)["signal_id"], "signal_new")
        with closing(sqlite3.connect(self.engine.signal_audit_file)) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM daily_signals").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT count(*) FROM audit_runs").fetchone()[0], 3)
            self.assertEqual(con.execute("SELECT count(*) FROM signal_factors").fetchone()[0], 0)
