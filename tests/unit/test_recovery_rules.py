import importlib
import json
import unittest
from dataclasses import FrozenInstanceError, replace

from tests.support.paths import ROOT
from tests.support.recovery_fixtures import daily_payload


class RecoveryRuleTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "quantagent_platform/recovery/contracts.py").is_file(),
                        "missing owned recovery API")
        self.c = importlib.import_module("quantagent_platform.recovery.contracts")
        self.r = importlib.import_module("quantagent_platform.recovery.rules")

    def snapshot(self):
        return self.r.freeze_snapshot(instance_id="fixture", run_id="run_fixture", kind="daily",
                                      date="2026-10-03", created_at="2026-10-03T08:00:00+08:00",
                                      payload=daily_payload())

    def event(self, step, status, detail=None):
        return self.c.RecoveryEvent(step + status, step, status,
                                   "2026-10-03T08:01:00+08:00", detail or {})

    def test_snapshot_is_frozen(self):
        snap = self.snapshot()
        with self.assertRaises(FrozenInstanceError):
            snap.payload_json = "{}"
        with self.assertRaises(self.c.RecoveryInvalidState):
            self.r.validate_snapshot(replace(snap, payload_json="{}"))
        self.assertEqual(json.loads(snap.payload_json)["report"], "中文日报\n原文本\n")

    def test_unknown_message_is_not_retryable_without_confirmation(self):
        rec = self.c.ExecutionRecord(self.snapshot(), 0, "pending", {}, ())
        rec = self.r.transition(rec, self.event("message", "running"))
        rec = self.r.transition(rec, self.event("message", "unknown"))
        with self.assertRaises(self.c.RecoveryInvalidState):
            self.r.transition(rec, self.event("message", "running"))
        rec = self.r.transition(rec, self.event("message", "failed", {"source": "manual"}))
        self.assertEqual(self.r.transition(rec, self.event("message", "running")).steps["message"], "running")
        rec = self.r.transition(rec, self.event("task", "abandoned", {"reason": "fixture"}))
        with self.assertRaises(self.c.RecoveryInvalidState):
            self.r.transition(rec, self.event("message", "confirmed"))

    def test_memory_target_and_audit_freeze(self):
        snap = self.snapshot()
        capsule = json.loads(snap.payload_json)["capsule"]
        state = {"last_daily_capsule": {"date": "2026-10-02", "btc_bias": "neutral", "core_thesis": "old"},
                 "rolling_7d": [{"date": "2026-10-01", "bias": "neutral", "core": "first"},
                                {"date": "2026-10-01", "bias": "bullish", "core": "last"}]}
        target = self.r.build_memory_target(state, capsule, lambda value, size: str(value)[:size])
        self.assertEqual([x["date"] for x in target["rolling_7d"]], ["2026-10-01", "2026-10-02"])
        self.assertEqual(target["rolling_7d"][0]["core"], "last")
        self.assertEqual(self.r.build_memory_target(target, capsule, lambda v, n: str(v)[:n]), target)
        audit = self.r.freeze_audit_payload(snap, {"report": "succeeded", "message": "unknown",
                                                 "memory": "superseded"}, "2026-10-03T08:02:00+08:00")
        self.assertTrue(audit["run"]["report_written"])
        self.assertFalse(audit["run"]["wecom_sent"])
        self.assertFalse(audit["run"]["memory_saved"])
        rec = self.c.ExecutionRecord(snap, 0, "pending", {}, ())
        rec = self.r.transition(rec, self.event("audit_payload", "frozen", {"payload": audit}))
        changed = json.loads(json.dumps(audit))
        changed["run"]["wecom_sent"] = True
        with self.assertRaises(self.c.RecoveryConflict):
            self.r.transition(rec, self.event("audit_payload", "frozen", {"payload": changed}))
