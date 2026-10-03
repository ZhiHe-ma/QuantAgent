"""Hard process death and independent processes with real OS locks and SQLite."""
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from queue import Queue
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

from tests.support.paths import ROOT
from tests.support.recovery_fixtures import daily_payload, isolated_engine
from quantagent_platform.recovery.contracts import RecoveryBusy
from quantagent_platform.recovery.sqlite_store import SQLiteRecoveryStore
from quantagent_platform.legacy_daily_recovery import run_daily_recovery

CHILD = "from pathlib import Path; import sys; from tests.support.recovery_fixtures import recovery_child; recovery_child(Path(sys.argv[1]), sys.argv[2], sys.argv[3])"


class ProcessRecoveryTests(unittest.TestCase):
    def run_child(self, root, operation, point=""):
        return subprocess.run([sys.executable, "-c", CHILD, str(root), operation, point], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def hold_child(self, root, operation, point=""):
        process = subprocess.Popen([sys.executable, "-c", CHILD, str(root), operation, point], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        self.addCleanup(self.close_child, process)
        queue = Queue()
        def read_ready():
            for line in process.stdout:
                if line.strip() == "READY": queue.put(True); return
            queue.put(False)
        reader = threading.Thread(target=read_ready, daemon=True);reader.start()
        ready = queue.get(timeout=20)
        self.assertTrue(ready, "child exited before barrier")
        reader.join(timeout=2)
        return process

    def close_child(self, process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def release(self, process):
        output, error = process.communicate("release\n", timeout=30)
        self.assertEqual(process.returncode, 0, output+error)

    def audit_counts(self, daily):
        path = daily / "signal_audit.sqlite3"
        if not path.exists(): return (0, 0, 0)
        with closing(sqlite3.connect(path)) as con:
            return tuple(con.execute("SELECT count(*) FROM "+table).fetchone()[0] for table in
                         ("audit_runs", "daily_signals", "signal_factors"))

    def test_process_death_releases_locks_and_reconciles_effects(self):
        for point in ("report", "message", "memory", "audit"):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temp:
                root = Path(temp);daily = root/"10_DailyNotes"
                crashed = self.run_child(root, "crash", point)
                self.assertEqual(crashed.returncode, 23, crashed.stdout+crashed.stderr)
                store = SQLiteRecoveryStore(str(daily))
                record = store.find_daily("2026-10-03")
                original = record.snapshot
                counts = self.audit_counts(daily)
                model_before = (root/"model-effects.log").read_bytes()
                with store.lock("daily"): pass
                with store.lock("projection"): pass
                resumed = self.run_child(root, "resume")
                self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
                self.assertEqual(store.get(original.run_id).snapshot, original)
                self.assertEqual((root/"model-effects.log").read_bytes(), model_before)
                self.assertEqual((root/"send-effects.log").read_text(encoding="utf-8").count("accepted"), 1)
                self.assertEqual(self.audit_counts(daily), (1, 1, 1))
                if point == "audit": self.assertEqual(self.audit_counts(daily), counts)
                if point == "message": self.assertEqual(store.get(original.run_id).steps["message"], "unknown")
                else: self.assertEqual(store.get(original.run_id).state, "completed")
                again = self.run_child(root, "resume")
                self.assertEqual(again.returncode, 0, again.stdout+again.stderr)
                self.assertEqual(self.audit_counts(daily), (1, 1, 1))

    def test_concurrent_daily_and_monitor_respect_scoped_locks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);store = SQLiteRecoveryStore(str(root/"10_DailyNotes"))
            for scope in ("daily", "monitor", "projection"):
                process = self.hold_child(root, "hold", scope)
                with self.assertRaises(RecoveryBusy):
                    with store.lock(scope): pass
                if scope == "daily":
                    with store.lock("monitor"): pass
                if scope == "monitor":
                    with store.lock("daily"): pass
                self.release(process)
                with store.lock(scope): pass
            daily = self.hold_child(root, "infer-daily")
            monitor = self.hold_child(root, "infer-monitor")
            for scope in ("daily", "monitor"):
                with self.assertRaises(RecoveryBusy):
                    with store.lock(scope): pass
            # Neither suspended inference holds the shared file-projection lock.
            with store.lock("projection"): pass
            self.release(monitor)
            self.release(daily)
            old = store.find_daily("2026-10-03")
            with isolated_engine(root) as (_, engine):
                now = datetime(2026, 10, 4, 8, tzinfo=timezone(timedelta(hours=8)))
                engine.fetch_market_signals = Mock(return_value={"crypto": {"BTC_Price": 60000, "BTC_24h_Chg%": 1, "Fear_Greed": 50}, "macro": {"S&P500_Chg%": 0, "VIX_Volatility": 16}})
                engine.request_deepseek = Mock(side_effect=["next-day research", json.dumps(daily_payload("2026-10-04")["capsule"])])
                engine.push_to_wecom = Mock(return_value=True)
                run_daily_recovery(replace(engine.daily_ports(), now=lambda: now))
                before = Path(engine.memory_file).read_bytes()
                self.assertEqual(engine.project_daily_memory(old.snapshot).status, "superseded")
                self.assertEqual(Path(engine.memory_file).read_bytes(), before)
