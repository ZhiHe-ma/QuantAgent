"""Injected storage and fixed P5 findings across real offline worker processes."""
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

from quantagent_platform.contracts import DataPacket
from quantagent_platform.p5_coordinator import P5Coordinator
from quantagent_platform.p5_registry import ApprovedRunRegistry
from quantagent_platform.p5_review import render_review_report
from tests.support.paths import ROOT
from tests.support.p5_samples import build_approved_source


class P5BoundaryIntegrationTests(unittest.TestCase):
    def test_explicit_services_and_falsey_ledger_do_not_create_default_ledger(self):
        ports = importlib.import_module("quantagent_platform.p5_ports")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()

            class Ledger:
                def __bool__(self):
                    return False

            ledger = Ledger()
            ledger.root = root
            services = Mock(wraps=ports.get_p5_services())
            coordinator = P5Coordinator(root / "unused.json", root, root,
                                        ROOT / "policies/p5_sec_route.v1.json",
                                        ledger=ledger, services=services)
            self.assertIs(ledger, coordinator.ledger)
            services.prepare_run_root.assert_called_once()
            services.new_ledger.assert_not_called()
            self.assertFalse((root / "p5_handoff.sqlite3").exists())

    def test_fixed_findings_report_and_audit_match_pre_refactor_fixture(self):
        expected = json.loads((ROOT / "tests/fixtures/p5_review_compatibility.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            approved, runs = build_approved_source(root)
            coordinator = P5Coordinator(approved, runs, root / "chains", ROOT / "policies/p5_sec_route.v1.json")
            result = coordinator.run("synthetic-p4", "compatibility-request")
            self.assertEqual("completed", result.status)
            packet_path = root / "chains" / result.child_run_id / "02-review-sec-evidence.json"
            findings = dict(DataPacket.from_dict(json.loads(packet_path.read_text(encoding="utf-8"))).records[0])
            for name in ("coordinator_id", "parent_run_id", "handoff_sha256"):
                findings.pop(name)
            self.assertEqual(expected["findings"], findings)
            self.assertEqual(expected["review_sha256"], hashlib.sha256(
                render_review_report(findings, expected["reviewed_at"])).hexdigest())
            audit = coordinator.ledger.get(result.chain_id)
            self.assertEqual(expected["audit"], {
                "status": result.status, "handoff_calls": result.handoff_calls,
                "model_cost_minor": result.model_cost_minor, "failure_code": result.failure_code,
                "event_count": len(audit["events"]),
            })
            self.assertEqual(result, coordinator.run("synthetic-p4", "compatibility-request"))
            source = ApprovedRunRegistry.load(approved, runs).resolve("synthetic-p4")
            self.assertEqual(source, type(source).from_pins(source.to_pins(), runs))

    def test_fresh_package_startup_installs_services_without_opening_database(self):
        code = """
from unittest.mock import patch
from pathlib import Path
with patch('sqlite3.connect', side_effect=AssertionError('startup must not open SQLite')), \
     patch.object(Path, 'mkdir', side_effect=AssertionError('startup must not create run directories')):
    from quantagent_platform.p5_ports import get_p5_services, strict_json
    assert get_p5_services() is not None
    assert strict_json(b'{"value":1}') == {'value':1}
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                                text=True, encoding="utf-8", timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_storage_port_retains_bounded_regular_file_checks(self):
        ports = importlib.import_module("quantagent_platform.p5_ports")
        services = ports.get_p5_services()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_bytes(b'{}')
            self.assertEqual(b'{}', services.read_file(path, 2))
            self.assertTrue(services.path_signatures(path))
            with self.assertRaises(ports.ApprovedSourceError):
                services.read_file(path, 1)
            with self.assertRaises(ports.ApprovedSourceError):
                services.read_file(Path(directory), 2)


if __name__ == "__main__":
    unittest.main()
