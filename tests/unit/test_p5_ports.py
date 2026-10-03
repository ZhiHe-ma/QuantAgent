"""Pure P5 data/validation contracts and their legacy import identities."""
import importlib
from pathlib import Path
import unittest
from unittest.mock import patch

from quantagent_platform.p5_handoff import HandoffError, RoutePolicy
from quantagent_platform import p5_ledger, p5_registry
from tests.support.paths import ROOT


class P5PortRuleTests(unittest.TestCase):
    def test_strict_json_preserves_error_identity_and_rejection_rules(self):
        ports = importlib.import_module("quantagent_platform.p5_ports")
        self.assertIs(ports.ApprovedSourceError, p5_registry.ApprovedSourceError)
        self.assertIs(ports.strict_json, p5_registry.strict_json)
        self.assertEqual({"value": 1}, ports.strict_json(b'{"value":1}'))
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e10000}', b'[]', b'\xff'):
            with self.subTest(raw=raw), self.assertRaises(ports.ApprovedSourceError):
                ports.strict_json(raw)

    def test_bounded_identifier_rule_and_ledger_error_are_shared(self):
        ports = importlib.import_module("quantagent_platform.p5_ports")
        self.assertIs(ports.LedgerError, p5_ledger.LedgerError)
        self.assertEqual("run-001", ports.validate_identifier("run-001", "run_id"))
        for value in ("../escape", "", "a" * 129, None, "unsafe/name"):
            with self.subTest(value=value), self.assertRaises(p5_ledger.LedgerError):
                ports.validate_identifier(value, "run_id")

    def test_route_policy_can_be_validated_without_storage_access(self):
        raw = (ROOT / "policies/p5_sec_route.v1.json").read_bytes()
        with patch("quantagent_platform.p5_handoff.get_p5_services", side_effect=AssertionError("pure validation must not read storage")):
            policy = RoutePolicy.from_bytes(raw)
            self.assertEqual("quantagent.p5_sec_route.v1", policy.version)
            for invalid in (b'{"bad":1}', b'x' * (64 * 1024 + 1), "not bytes"):
                with self.subTest(invalid_type=type(invalid)), self.assertRaises(HandoffError):
                    RoutePolicy.from_bytes(invalid)

    def test_evidence_types_and_pin_serialization_remain_public(self):
        ports = importlib.import_module("quantagent_platform.p5_ports")
        self.assertIs(ports.ApprovedRun, p5_registry.ApprovedRun)
        self.assertIs(ports.SecEvidence, p5_registry.SecEvidence)
        source = p5_registry.ApprovedRun(
            "source", "run-001", Path("unused"), "a" * 64, "b" * 64, "c" * 64,
            {"raw": "d" * 64}, "sec-industry-peers", "1.0.0", "source.plugin", "1.0.0",
        )
        with patch.object(ports, "get_p5_services", side_effect=AssertionError("pin serialization is pure")):
            self.assertEqual("source", source.to_pins()["approved_source_id"])
            pins = source.to_pins()
            pins["raw_sha256"]["raw"] = "changed"
            self.assertEqual("d" * 64, source.raw_sha256["raw"])


if __name__ == "__main__":
    unittest.main()
