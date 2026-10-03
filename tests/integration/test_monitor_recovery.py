"""Durable original-news retries using real temporary projections and journal."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import importlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from tests.support.paths import ROOT
from tests.support.recovery_fixtures import isolated_engine, news_payload
from quantagent_platform.recovery.contracts import RecoveryBusy, RecoveryInvalidState, StepResult
from quantagent_platform.recovery.sqlite_store import SQLiteRecoveryStore

NOW = datetime(2026, 10, 3, 23, 59, tzinfo=timezone(timedelta(hours=8)))


class StopCycle(BaseException):
    pass


class MonitorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "quantagent_platform/legacy_monitor_recovery.py").is_file(), "missing Monitor recovery workflow")
        self.flow = importlib.import_module("quantagent_platform.legacy_monitor_recovery")

    def ports(self, engine, *, news=None, at=NOW):
        engine.fetch_crypto_flash_news = Mock(return_value=[news_payload()["news"]] if news is None else news)
        engine.request_deepseek = Mock(return_value='{"sentiment":"中性","weight":"Medium","reason":"合成因子"}')
        return replace(engine.monitor_ports(), now=lambda: at, sleep=Mock(side_effect=StopCycle))

    def cycle(self, ports):
        with self.assertRaises(StopCycle): self.flow.run_monitor_recovery(ports)

    def test_pending_news_survives_midnight_and_source_removal(self):
        with tempfile.TemporaryDirectory() as temp:
            with isolated_engine(Path(temp)) as (_, engine):
                ports = self.ports(engine)
                self.cycle(replace(ports, project_news=Mock(return_value=StepResult("failed", {"error_code": "disk"}))))
                original = engine.recovery_store.list_open("monitor")[0]
                self.assertEqual(engine.request_deepseek.call_count, 1)
            with isolated_engine(Path(temp)) as (_, engine):
                ports = self.ports(engine, news=[], at=NOW+timedelta(minutes=2))
                engine.request_deepseek.side_effect = AssertionError("repeated inference")
                self.cycle(ports)
                self.assertEqual(engine.recovery_store.get(original.snapshot.run_id).state, "completed")
                self.assertEqual(len(engine.capture_monitor_state("2026-10-03")["buffer"]), 1)
                self.assertEqual(engine.capture_monitor_state("2026-10-04")["buffer"], [])
                engine.request_deepseek.assert_not_called()

    def test_buffer_ack_then_dedup_failure_has_one_factor(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine)
            original = ports.project_news
            def fail_dedup(record, projection):
                return StepResult("failed", {}) if projection == "dedup" else original(record, projection)
            self.cycle(replace(ports, project_news=fail_dedup))
            self.assertEqual(len(engine.capture_monitor_state("2026-10-03")["buffer"]), 1)
            self.cycle(ports)
            state = engine.capture_monitor_state("2026-10-03")
            self.assertEqual(len(state["buffer"]), 1)
            self.assertEqual(state["dedup"], ["news_fixture"])
            self.assertEqual(len(state["fingerprint"]), 1)
            self.assertEqual(engine.request_deepseek.call_count, 1)

    def test_storage_failure_does_not_spend_parse_budget(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine)
            self.cycle(replace(ports, project_news=Mock(side_effect=OSError("disk"))))
            record = engine.recovery_store.list_open("monitor")[0]
            frozen = next(e.detail for e in record.events if e.step == "model" and e.status == "succeeded")
            self.assertEqual(frozen["attempts"], 0)
            from quantagent_platform.legacy_recovery_actions import run_recovery_action
            engine.fetch_crypto_flash_news.reset_mock()
            ports.sleep.reset_mock()
            run_recovery_action(engine.recovery_store, action="retry", run_id=record.snapshot.run_id, monitor=ports)
            engine.fetch_crypto_flash_news.assert_not_called()
            ports.sleep.assert_not_called()
            self.assertEqual(engine.request_deepseek.call_count, 1)
            self.assertEqual(next(e.detail for e in engine.recovery_store.get(record.snapshot.run_id).events
                                  if e.step == "model" and e.status == "succeeded"), frozen)

    def test_low_weight_and_poison_quarantine_finish_only_after_projection(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine)
            engine.request_deepseek.return_value = '{"sentiment":"中性","weight":"Low","reason":"普通观点"}'
            self.cycle(ports)
            state = engine.capture_monitor_state("2026-10-03")
            self.assertEqual(state["buffer"], [])
            self.assertEqual(state["dedup"], ["news_fixture"])
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.request_deepseek.return_value = "not-json"
            self.cycle(ports)
            self.assertEqual(engine.recovery_store.list_open("monitor")[0].steps["model"], "failed")
            self.cycle(ports)
            original = ports.project_news
            def fail_quarantine(record, projection):
                return StepResult("failed", {}) if projection == "quarantine" else original(record, projection)
            self.cycle(replace(ports, project_news=fail_quarantine))
            self.assertEqual(engine.request_deepseek.call_count, 3)
            self.assertEqual(engine.capture_monitor_state("2026-10-03")["dedup"], [])
            self.cycle(ports)
            state = engine.capture_monitor_state("2026-10-03")
            self.assertEqual(next(iter(state["quarantine"].values()))["status"], "quarantined")
            self.assertEqual(state["dedup"], ["news_fixture"])
            self.assertEqual(engine.request_deepseek.call_count, 3)
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine);engine.request_deepseek.return_value = "not-json"
            self.cycle(ports)
            engine.request_deepseek.return_value = '{"sentiment":"中性","weight":"Medium","reason":"重试成功"}'
            self.cycle(ports)
            self.assertEqual(engine.capture_monitor_state("2026-10-03")["quarantine"], {})
            self.assertEqual(engine.recovery_store.list_open("monitor"), [])
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            ports = self.ports(engine)
            fingerprint = ports.news_fingerprint(news_payload()["news"])
            Path(engine.failed_news_file).write_text(json.dumps({fingerprint: {"id": "news_fixture", "fingerprint": fingerprint,
                "attempts": 3, "status": "quarantined"}}), encoding="utf-8")
            self.cycle(ports)
            engine.request_deepseek.assert_not_called()
            self.assertEqual(engine.capture_monitor_state("2026-10-03")["dedup"], ["news_fixture"])

    def test_legacy_malformed_or_conflicting_news_files_stop(self):
        for name, value in [("dedup_file", "{broken"), ("fingerprint_file", "{}"), ("failed_news_file", "[]"),
                            ("buffer", "{}"), ("buffer", '[{"id":"a","fingerprint":"f","reason":"one"},{"id":"a","fingerprint":"f","reason":"two"}]')]:
            with self.subTest(name=name, value=value), tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
                ports = self.ports(engine)
                path = Path(engine._get_buffer_path("2026-10-03") if name == "buffer" else getattr(engine, name))
                path.write_text(value, encoding="utf-8")
                before = path.read_bytes()
                with self.assertRaises(RecoveryInvalidState): self.flow.run_monitor_recovery(ports)
                engine.request_deepseek.assert_not_called()
                self.assertEqual(path.read_bytes(), before)

    def test_monitor_dry_run_has_no_recovery_or_projection_writes(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp), dry_run=True) as (_, engine):
            self.cycle(self.ports(engine))
            self.assertFalse(Path(engine.daily_dir).exists())

    def test_recovery_respects_original_cycle_budget(self):
        with tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
            news = [dict(news_payload()["news"], id=str(i), title="合成"+str(i)) for i in range(5)]
            ports = replace(self.ports(engine, news=news), max_news_per_cycle=2)
            engine.request_deepseek.return_value = "not-json"
            self.cycle(ports)
            self.assertEqual(engine.request_deepseek.call_count, 2)
            engine.request_deepseek.return_value = '{"sentiment":"中性","weight":"Medium","reason":"重试"}'
            self.cycle(ports)
            self.assertEqual(engine.request_deepseek.call_count, 4)

    def test_projection_contention_yields_without_stopping_monitor(self):
        for point in ("startup", "after_model"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
                ports = self.ports(engine)
                peer = SQLiteRecoveryStore(engine.daily_dir)
                ready, release = threading.Event(), threading.Event()
                errors, waits = [], []
                def hold_daily_projection():
                    try:
                        with peer.lock("daily"), peer.lock("projection"):
                            ready.set()
                            release.wait(10)
                    except BaseException as exc:
                        errors.append(exc)
                        ready.set()
                holder = threading.Thread(target=hold_daily_projection, daemon=True)
                def start_holder():
                    holder.start()
                    self.assertTrue(ready.wait(5), "projection holder did not start")
                    self.assertEqual(errors, [])
                if point == "startup":
                    start_holder()
                else:
                    def infer(*args, **kwargs):
                        start_holder()
                        return '{"sentiment":"中性","weight":"Medium","reason":"合成因子"}'
                    engine.request_deepseek.side_effect = infer
                def sleep(seconds):
                    waits.append(seconds)
                    if seconds == 1:
                        release.set()
                        holder.join(5)
                        self.assertFalse(holder.is_alive())
                    elif not engine.recovery_store.list_open("monitor"):
                        raise StopCycle()
                ports = replace(ports, sleep=sleep)
                try:
                    self.cycle(ports)
                finally:
                    release.set()
                    if holder.ident is not None:
                        holder.join(5)
                self.assertEqual(errors, [])
                self.assertIn(1, waits)
                self.assertEqual(engine.request_deepseek.call_count, 1)
                self.assertEqual(engine.capture_monitor_state("2026-10-03")["dedup"], ["news_fixture"])
                with peer.lock("monitor"):
                    with self.assertRaises(RecoveryBusy):
                        self.flow.run_monitor_recovery(ports)

    def test_same_news_id_is_deduplicated_after_confirmed_projection(self):
        for fail_fingerprint in (False, True):
            with self.subTest(fail_fingerprint=fail_fingerprint), tempfile.TemporaryDirectory() as temp, isolated_engine(Path(temp)) as (_, engine):
                news = news_payload()["news"]
                ports = self.ports(engine, news=[news, dict(news, title="同一 ID 的更新标题", body="changed")])
                owned = ports.project_news
                def project(record, projection):
                    if fail_fingerprint and projection == "fingerprint":
                        return StepResult("failed", {"error_code": "disk"})
                    return owned(record, projection)
                self.cycle(replace(ports, project_news=project))
                self.assertEqual(engine.request_deepseek.call_count, 1)
                state = engine.capture_monitor_state("2026-10-03")
                self.assertEqual(state["dedup"], [news["id"]])
                self.assertEqual(len(state["buffer"]), 1)
                if fail_fingerprint:
                    self.assertEqual(len(engine.recovery_store.list_open("monitor")), 1)
                    engine.fetch_crypto_flash_news.return_value = []
                    self.cycle(ports)
                    self.assertEqual(engine.recovery_store.list_open("monitor"), [])
                    self.assertEqual(engine.request_deepseek.call_count, 1)
