"""Recover original research against real temporary files and two SQLite stores."""
from contextlib import closing
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import importlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tests.support.paths import ROOT
from tests.support.recovery_fixtures import daily_payload, isolated_engine
from quantagent_platform.recovery.contracts import DeliveryResult, RecoveryError, RecoveryInvalidState, StepResult

NOW = datetime(2026, 10, 3, 8, tzinfo=timezone(timedelta(hours=8)))


class DailyRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "quantagent_platform/legacy_daily_recovery.py").is_file(), "missing Daily recovery workflow")
        self.flow = importlib.import_module("quantagent_platform.legacy_daily_recovery")
        self.actions = importlib.import_module("quantagent_platform.legacy_recovery_actions")

    def ports(self, engine):
        engine.fetch_market_signals = Mock(return_value={"timestamp": "fixture", "crypto": {"BTC_Price": 60000, "BTC_24h_Chg%": 1, "Fear_Greed": 50}, "macro": {"S&P500_Chg%": 0, "VIX_Volatility": 16}})
        engine.request_deepseek = Mock(side_effect=["合成研究", json.dumps(daily_payload()["capsule"])])
        engine.push_to_wecom = Mock(return_value=True)
        return replace(engine.daily_ports(), now=lambda: NOW)

    def action(self, engine, action, **kwargs):
        record = engine.recovery_store.find_daily("2026-10-03")
        return self.actions.run_recovery_action(engine.recovery_store, action=action, run_id=record.snapshot.run_id, **kwargs)

    def test_invalid_capsule_or_snapshot_failure_has_no_delivery(self):
        for point in ("capsule", "snapshot"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (module, engine):
                ports = self.ports(engine)
                if point == "capsule":
                    ports = replace(ports, generate_memory_capsule=Mock(side_effect=module.DeepSeekError("invalid capsule")))
                    context = self.assertRaises(module.DeepSeekError)
                else:
                    engine.recovery_store.create = Mock(side_effect=RecoveryError("journal unavailable"))
                    context = self.assertRaises(RecoveryError)
                with context:
                    self.flow.run_daily_recovery(ports)
                self.assertFalse(list(Path(engine.daily_dir).glob("*.md")))
                self.assertFalse(Path(engine.memory_file).exists())
                self.assertFalse(Path(engine.signal_audit_file).exists())
                engine.push_to_wecom.assert_not_called()

    def test_resume_after_each_daily_boundary_reuses_snapshot(self):
        for step in ("report", "message", "memory", "audit"):
            for lost_ack in (False, True):
                with self.subTest(step=step, lost_ack=lost_ack), tempfile.TemporaryDirectory() as temp:
                    with isolated_engine(Path(temp)) as (_, engine):
                        ports = self.ports(engine)
                        if lost_ack:
                            append = engine.recovery_store.append_event
                            def fail_ack(run_id, event, **kwargs):
                                if event.step == step and event.status in {"succeeded", "confirmed"}:
                                    raise RecoveryError("lost acknowledgement")
                                return append(run_id, event, **kwargs)
                            with patch.object(engine.recovery_store, "append_event", side_effect=fail_ack):
                                with self.assertRaises(RecoveryError):
                                    self.flow.run_daily_recovery(ports)
                        else:
                            field = {"report": "project_report", "message": "send_message", "memory": "project_memory", "audit": "commit_audit"}[step]
                            callback = Mock(return_value=False) if step == "message" else Mock(side_effect=OSError("delivery unavailable"))
                            self.flow.run_daily_recovery(replace(ports, **{field: callback}))
                        record = engine.recovery_store.find_daily("2026-10-03")
                        self.assertEqual(record.state, "pending")
                        original = record.snapshot
                    with isolated_engine(Path(temp)) as (_, engine):
                        ports = self.ports(engine)
                        ports.fetch_market_signals.side_effect = AssertionError("repeated market research")
                        ports.request_deepseek.side_effect = AssertionError("repeated model research")
                        self.flow.run_daily_recovery(ports)
                        record = engine.recovery_store.get(original.run_id)
                        self.assertEqual(record.snapshot, original)
                        if step == "message":
                            self.assertEqual(record.steps["message"], "unknown")
                            engine.push_to_wecom.assert_not_called()
                        else:
                            self.assertEqual(record.state, "completed")
                        ports.fetch_market_signals.assert_not_called()
                        ports.request_deepseek.assert_not_called()
                        with closing(sqlite3.connect(engine.signal_audit_file)) as con:
                            self.assertEqual(con.execute("SELECT count(*) FROM daily_signals").fetchone()[0], 1)

    def test_unknown_confirmation_and_explicit_retry(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.push_to_wecom.return_value = False
            self.flow.run_daily_recovery(ports)
            self.flow.run_daily_recovery(ports)
            self.assertEqual(engine.push_to_wecom.call_count, 1)
            self.action(engine, "confirm-not-sent")
            self.flow.run_daily_recovery(ports)
            self.assertEqual(engine.push_to_wecom.call_count, 1)
            engine.push_to_wecom.return_value = True
            self.action(engine, "retry", daily=ports)
            self.assertEqual(engine.push_to_wecom.call_count, 2)
            before = engine.recovery_store.find_daily("2026-10-03").revision
            self.action(engine, "confirm-sent")
            self.action(engine, "confirm-sent")
            self.assertEqual(engine.recovery_store.find_daily("2026-10-03").revision, before)

    def test_audit_payload_remains_frozen_after_later_confirmation(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.push_to_wecom.return_value = False
            self.flow.run_daily_recovery(ports)
            self.action(engine, "confirm-sent")
            self.flow.run_daily_recovery(ports)
            with closing(sqlite3.connect(engine.signal_audit_file)) as con:
                self.assertEqual(con.execute("SELECT wecom_sent FROM audit_runs").fetchone()[0], 0)
                self.assertEqual(con.execute("SELECT count(*) FROM daily_signals").fetchone()[0], 1)

    def test_first_channel_binding_and_channel_change(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp), wecom_url="") as (_, engine):
            ports = self.ports(engine)
            self.flow.run_daily_recovery(ports)
            self.assertEqual(self.flow.run_daily_recovery(ports), {"status": "skipped", "date": "2026-10-03"})
            engine.wecom_url = "https://example.invalid/later"
            self.action(engine, "retry", daily=ports)
            self.assertEqual(engine.push_to_wecom.call_count, 1)
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.push_to_wecom.return_value = False
            self.flow.run_daily_recovery(ports)
            self.action(engine, "confirm-not-sent")
            engine.wecom_url = "https://example.invalid/changed"
            self.action(engine, "retry", daily=ports)
            self.assertEqual(engine.push_to_wecom.call_count, 1)
            self.assertEqual(engine.recovery_store.find_daily("2026-10-03").steps["message"], "needs_review")

    def test_report_failure_cannot_implicitly_bind_first_channel(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp), wecom_url="") as (_, engine):
            ports = self.ports(engine)
            self.flow.run_daily_recovery(replace(ports, project_report=lambda _: StepResult("failed", {"error_code": "disk"})))
            original = engine.recovery_store.find_daily("2026-10-03")
            self.assertIsNone(json.loads(original.snapshot.payload_json)["channel_id"])
            self.assertEqual(original.steps["message"], "pending")
            engine.wecom_url = "https://example.invalid/first-channel"
            channel = engine.recovery_channel_id()
            send = Mock(return_value=DeliveryResult("failed", "provider", channel, "rejected"))
            ports = replace(ports, send_message=send)
            self.flow.run_daily_recovery(ports)
            send.assert_not_called()
            record = engine.recovery_store.get(original.snapshot.run_id)
            self.assertEqual(record.steps["message"], "not_configured")
            self.assertFalse(any(e.status == "retry_requested" for e in record.events))
            self.action(engine, "retry", daily=ports)
            self.assertEqual(send.call_count, 1)
            record = engine.recovery_store.get(original.snapshot.run_id)
            self.assertEqual(record.snapshot, original.snapshot)
            self.assertEqual(next(e.detail["channel_id"] for e in record.events if e.status == "retry_requested"), channel)
            engine.wecom_url = "https://example.invalid/different-channel"
            self.action(engine, "retry", daily=ports)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(engine.recovery_store.get(original.snapshot.run_id).steps["message"], "needs_review")

    def test_recover_cli_honors_dotenv_dry_run_without_engine(self):
        script = '''import json, os, sys
from pathlib import Path
from unittest.mock import patch
from dotenv import load_dotenv as real_load_dotenv
from tests.support.recovery_fixtures import isolated_engine
with isolated_engine(Path(sys.argv[1])) as (module, _):
    os.environ.pop("DRY_RUN", None)
    module.load_dotenv = real_load_dotenv
    with patch.object(module, "QuantAgent", side_effect=AssertionError("preview constructed research engine")):
        result = module.main(["--mode", "recover", "--action", sys.argv[3], "--run-id", sys.argv[2], "--reason", "fixture"])
    assert result["status"] == "dry_run", result
'''
        child_env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONPATH=os.pathsep.join(sys.path))
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine)
            engine.push_to_wecom.return_value = False
            self.flow.run_daily_recovery(ports)
            run_id = engine.recovery_store.find_daily("2026-10-03").snapshot.run_id
            (Path(temp) / ".env").write_text("DRY_RUN=true\n", encoding="utf-8")
            before = {p.name: p.read_bytes() for p in Path(engine.daily_dir).iterdir()}
            for action in ("abandon", "confirm-sent", "confirm-not-sent", "retry"):
                with self.subTest(action=action):
                    proc = subprocess.run([sys.executable, "-c", script, temp, run_id, action], cwd=ROOT,
                                          env=child_env,
                                          capture_output=True, text=True, encoding="utf-8", timeout=20)
                    self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                    self.assertEqual(before, {p.name: p.read_bytes() for p in Path(engine.daily_dir).iterdir()})

    def test_daily_cli_reports_pending_failure_and_recovery_id(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (module, engine):
            ports = replace(self.ports(engine), project_report=lambda _: StepResult("failed", {"error_code": "report_io"}))
            engine.run_daily_pipeline = lambda: self.flow.run_daily_recovery(ports)
            output = io.StringIO()
            with patch.object(module, "QuantAgent", return_value=engine), redirect_stdout(output):
                with self.assertRaises(SystemExit) as failure:
                    module.main(["--mode", "daily"])
            self.assertEqual(failure.exception.code, 2)
            result = json.loads(output.getvalue())
            record = engine.recovery_store.find_daily("2026-10-03")
            self.assertEqual(result["status"], "pending")
            self.assertEqual(result["run_id"], record.snapshot.run_id)
            self.assertEqual(result["steps"]["report"], "failed")
            self.assertIn("report", result["blocked_steps"])

    def test_status_without_configuration_and_dry_actions_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            script = '''import runpy, sys
from pathlib import Path
from unittest.mock import patch
from tests.support.recovery_fixtures import isolated_engine
with isolated_engine(Path(sys.argv[1]), dry_run=True) as (module, engine):
    with patch.object(module, "QuantAgent", side_effect=AssertionError("status constructed engine")):
        module.main(["--mode", "recover", "--action", "status"])
assert not (Path(sys.argv[1])/"10_DailyNotes").exists()
'''
            proc = subprocess.run([sys.executable, "-c", script, temp], cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stdout+proc.stderr)
            with isolated_engine(Path(temp)) as (_, engine):
                self.flow.run_daily_recovery(self.ports(engine))
                before = {p.name: p.read_bytes() for p in Path(engine.daily_dir).iterdir()}
                for action in ("status", "retry", "confirm-sent", "confirm-not-sent", "abandon"):
                    self.action(engine, action, dry_run=True, reason="fixture")
                self.assertEqual(before, {p.name: p.read_bytes() for p in Path(engine.daily_dir).iterdir()})

    def test_force_legacy_partial_and_abandon_rules(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.push_to_wecom.return_value = False
            self.flow.run_daily_recovery(ports)
            first = engine.recovery_store.find_daily("2026-10-03").snapshot.run_id
            self.flow.run_daily_recovery(replace(ports, force_daily_run=True))
            self.assertEqual(engine.recovery_store.find_daily("2026-10-03").snapshot.run_id, first)
            with self.assertRaises(RecoveryInvalidState): self.action(engine, "abandon")
            self.action(engine, "abandon", reason="user cancelled")
            with self.assertRaises(RecoveryInvalidState): self.action(engine, "retry", daily=ports)
            ports = self.ports(engine)
            self.flow.run_daily_recovery(ports)
            self.assertNotEqual(engine.recovery_store.find_daily("2026-10-03").snapshot.run_id, first)
            self.assertEqual(engine.recovery_store.get(first).state, "abandoned")
            ports = self.ports(engine)
            self.flow.run_daily_recovery(replace(ports, force_daily_run=True))
            self.assertEqual(engine.request_deepseek.call_count, 2)
        for complete in (False, True):
            with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
                ports = self.ports(engine)
                (Path(engine.daily_dir)/"2026-10-03.md").write_text("legacy", encoding="utf-8")
                if complete: Path(engine.memory_file).write_text(json.dumps(daily_payload()["memory_target"]), encoding="utf-8")
                result = self.flow.run_daily_recovery(ports)
                self.assertEqual(result["status"], "skipped" if complete else "needs_review")
                ports.fetch_market_signals.assert_not_called()
                self.assertFalse((Path(engine.daily_dir)/"quantagent_recovery.sqlite3").exists())
