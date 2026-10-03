"""Exercise real legacy consumers and persistence with only external services replaced."""
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import closing
from datetime import datetime
from unittest.mock import patch

from tests.support.paths import ROOT


def load_engine():
    requests = types.ModuleType("requests")
    def network_blocked(*args, **kwargs):
        raise AssertionError("unexpected network")
    requests.post = network_blocked
    requests.get = network_blocked
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *args, **kwargs: False
    with patch.dict(sys.modules, {"requests": requests, "yfinance": types.ModuleType("yfinance"), "dotenv": dotenv}):
        spec = importlib.util.spec_from_file_location("legacy_contract_under_test", ROOT / "agent_engine.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def capsule(date):
    return {"date": date, "risk_regime": "neutral", "btc_bias": "neutral", "confidence": 60,
            "core_thesis": "offline thesis", "invalid_if": "offline invalidation",
            "today_check": "offline check", "watch_items": []}


METRICS = {"timestamp": "2026-10-03 08:00:00", "crypto": {"BTC_Price": 60000, "BTC_24h_Chg%": 1.0, "Fear_Greed": 50},
           "macro": {"S&P500_Chg%": 0.5, "VIX_Volatility": 16.0}}


class LegacyPortsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / "quantagent_platform/legacy_ports.py").is_file(), "missing owned legacy ports")
        self.ports = importlib.import_module("quantagent_platform.legacy_ports")
        previous = self.ports.get_legacy_audit_factory()
        self.addCleanup(self.ports.configure_legacy_audit_factory, previous)

    def test_original_audit_aliases_and_source_hash_reach_payload(self):
        import signal_audit
        module = load_engine()
        self.assertIs(module.SignalAuditStore, signal_audit.SignalAuditStore)
        self.assertIs(module.calculate_data_quality, signal_audit.calculate_data_quality)
        self.assertIs(module.SignalAuditError, signal_audit.SignalAuditError)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"DRY_RUN": "true", "DEEPSEEK_API_KEY": "offline"}, clear=True):
            module.BASE_DIR = temp
            engine = module.QuantAgent()
            run, signal = engine.build_signal_audit_payload("2026-10-03", "2026-10-03T08:00:00+08:00",
                capsule("2026-10-03"), METRICS, [], {}, "offline analysis")
            digest = hashlib.sha256((ROOT / "agent_engine.py").read_bytes()).hexdigest()
            self.assertEqual(run["source_sha256"], digest)
            self.assertEqual(run["code_version"], "source:" + digest[:12])
            self.assertEqual(signal["data_quality_score"], 90.0)
            self.assertEqual(signal["quality_flags"], ["no_model_factors"])
            self.assertFalse(Path(engine.daily_dir).exists())

    def test_injected_audit_and_quality_are_consumed_by_real_daily_pipeline(self):
        from signal_audit import SignalAuditStore
        class TaggedStore(SignalAuditStore):
            def record_completed_signal(self, *args, **kwargs):
                result = super().record_completed_signal(*args, **kwargs)
                return dict(result, provider="injected")
        def quality(snapshot, factors, *, version_known, reconciled=False):
            if snapshot != METRICS or not version_known:
                raise AssertionError("incorrect quality input")
            return 37.0, ["injected_quality"]
        self.ports.configure_legacy_audit_factory(lambda: self.ports.LegacyAuditBindings(TaggedStore, quality))
        module = load_engine()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ,
                {"DRY_RUN": "false", "DEEPSEEK_API_KEY": "offline"}, clear=True):
            module.BASE_DIR = temp
            engine = module.QuantAgent()
            self.assertIsInstance(engine.signal_audit_store, TaggedStore)
            engine.fetch_market_signals = lambda: METRICS
            today = module.datetime.now().strftime("%Y-%m-%d")
            engine.request_deepseek = lambda *args, **kwargs: "offline analysis" if kwargs.get("use_r1") else json.dumps(capsule(today))
            result = engine.run_daily_pipeline()
            self.assertEqual(result["audit"]["provider"], "injected")
            self.assertIn("offline analysis", (Path(engine.daily_dir) / (today + ".md")).read_text(encoding="utf-8"))
            self.assertEqual(json.loads(Path(engine.memory_file).read_text(encoding="utf-8"))["last_daily_capsule"]["date"], today)
            with closing(sqlite3.connect(engine.signal_audit_file)) as connection:
                quality_row = connection.execute("SELECT data_quality_score, quality_flags_json FROM daily_signals").fetchone()
                delivery_row = connection.execute("SELECT report_written, wecom_sent, memory_saved FROM audit_runs").fetchone()
            self.assertEqual(quality_row, (37.0, '["injected_quality"]'))
            self.assertEqual(delivery_row, (1, 0, 1))

    def test_lazy_factory_binding_and_errors_do_not_create_storage(self):
        bootstrap = importlib.import_module("quantagent_platform.legacy_bootstrap")
        with patch.object(sqlite3, "connect", side_effect=AssertionError("startup database IO")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("startup filesystem IO")):
            bootstrap.install_legacy_audit_factory()
            bindings = self.ports.get_legacy_audit_bindings()
            self.assertTrue(callable(bindings.store_factory))
        previous = self.ports.get_legacy_audit_factory()
        with self.assertRaises(TypeError):
            self.ports.configure_legacy_audit_factory(None)
        self.assertIs(previous, self.ports.get_legacy_audit_factory())
        def failing_factory():
            raise OSError("factory failure")
        self.ports.configure_legacy_audit_factory(failing_factory)
        with self.assertRaisesRegex(OSError, "factory failure"):
            self.ports.get_legacy_audit_bindings()
        self.ports.configure_legacy_audit_factory(lambda: object())
        with self.assertRaises(TypeError):
            self.ports.get_legacy_audit_bindings()

    def test_monitor_public_ports_recover_retry_state_from_real_files(self):
        from quantagent_platform.legacy_workflows import run_monitor_pipeline
        class StopMonitor(BaseException):
            pass
        def stop(seconds):
            self.assertEqual(seconds, 180)
            raise StopMonitor
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            def read_json(path, default):
                return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else default
            def write_json(path, data):
                Path(path).write_text(json.dumps(data), encoding="utf-8")
                return True
            response = ["not-json"]
            ports = self.ports.MonitorPorts(dedup_file=str(base / "ids.json"), fingerprint_file=str(base / "fingerprints.json"),
                failed_news_file=str(base / "failures.json"), max_news_per_cycle=3, max_news_ai_retries=3, min_store_weight="Medium",
                read_json=read_json, write_json=write_json, get_buffer_path=lambda: str(base / "buffer.json"),
                fetch_crypto_flash_news=lambda: [{"id": "news-1", "title": "offline", "body": "fixture", "source": "test"}],
                news_fingerprint=lambda news: "fingerprint-1", clamp_str=lambda value, maximum: str(value)[:maximum],
                strip_json_fence=lambda value: value, request_deepseek=lambda *args, **kwargs: response[0],
                calibrate_factor_weight=lambda **kwargs: (kwargs["weight"], ""),
                weight_rank=lambda value: {"Low": 0, "Medium": 1, "High": 2, "Critical": 3}[value],
                prune_day_buffer=lambda value: value, now=lambda: datetime(2026, 10, 3, 8), sleep=stop)
            with self.assertRaises(StopMonitor):
                run_monitor_pipeline(ports)
            failure = read_json(ports.failed_news_file, {})["fingerprint-1"]
            self.assertEqual((failure["attempts"], failure["status"]), (1, "retry_pending"))
            self.assertFalse((base / "ids.json").exists())
            response[0] = '{"sentiment":"中性","weight":"Medium","reason":"offline reason"}'
            with self.assertRaises(StopMonitor):
                run_monitor_pipeline(ports)
            self.assertEqual(read_json(ports.failed_news_file, None), {})
            self.assertEqual(read_json(ports.dedup_file, None), ["news-1"])
            self.assertEqual(read_json(ports.fingerprint_file, None), ["fingerprint-1"])
            self.assertEqual(read_json(str(base / "buffer.json"), [])[0]["reason"], "offline reason")

    def test_signal_audit_first_import_and_cli_help_stay_offline(self):
        script = '''import io, runpy, sqlite3, sys, types
from contextlib import redirect_stdout
import signal_audit
from quantagent_platform.legacy_ports import get_legacy_audit_bindings, SignalAuditError
assert SignalAuditError is signal_audit.SignalAuditError
assert get_legacy_audit_bindings().store_factory is signal_audit.SignalAuditStore
def blocked(*args, **kwargs): raise AssertionError("unexpected external effect")
requests=types.ModuleType("requests"); requests.get=requests.post=blocked
dotenv=types.ModuleType("dotenv"); dotenv.load_dotenv=blocked
sys.modules.update(requests=requests, yfinance=types.ModuleType("yfinance"), dotenv=dotenv)
sqlite3.connect=blocked
sys.argv=["agent_engine.py", "--help"]
output=io.StringIO()
with redirect_stdout(output):
    try: runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as exc: assert exc.code == 0
    else: raise AssertionError("CLI help did not exit")
assert "{daily,weekly,monitor}" in output.getvalue()
import importlib
sys.modules.pop("quantagent_platform.legacy_ports")
unbound_ports=importlib.import_module("quantagent_platform.legacy_ports")
try: unbound_ports.get_legacy_audit_bindings()
except RuntimeError as exc: assert "not been configured" in str(exc)
else: raise AssertionError("unbound services did not fail explicitly")
print("audit-first startup and CLI help: passed")
'''
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("audit-first startup and CLI help: passed", result.stdout)


if __name__ == "__main__":
    unittest.main()
