"""Optional local acceptance against the pinned private P4 SEC run."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from quantagent_platform.contracts import DataPacket, canonical_json
from quantagent_platform.p5_coordinator import P5Coordinator


SOURCE_RUN_ID = "20260924T110650Z-52ae9d22"
PACKET_FILE_SHA256 = "336e35e65dde2470aaef4f2f6696dd03c4cef2e8fc5971dba71f2bfb2add4f98"
REPORT_SHA256 = "b63157e7d0dd0c5850df059c19c3f840cfee5ceaa239c68f3c0b750924c35f71"
RAW_SHA256 = {
    "sec-mara-submissions.json": "a8f515b490531db93815cca11a8fd50c9d143853c470f28c979227cb7bfa1f8d",
    "sec-mara-companyfacts.json": "696a02c3112da7a1db07f8e88fd8178dff153f7369ebca8bb4db39e930c11d49",
    "sec-riot-submissions.json": "90c78eb24b5eaffdb0d42f04485528e8871ab78f4a03b78e3ed2b32e5d48fe36",
    "sec-riot-companyfacts.json": "79218a3c69d48f60f3ec677215efe14c9a0cb6ae572e2d68f745e346e82ba124",
}


class PrivateP4LiveAcceptanceTests(unittest.TestCase):
    def test_private_p4_live_run_completes_offline_with_fixed_numbers(self) -> None:
        configured = os.environ.get("QUANTAGENT_P5_APPROVED_P4_ROOT")
        if not configured or not (Path(configured) / SOURCE_RUN_ID).is_dir():
            self.skipTest("pinned private P4 run is absent")
        approved_root = Path(configured)
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary)
            registry_path = private / "approved.json"
            registry_path.write_text(canonical_json({
                "registry_version": "quantagent.sec_approved_run.v1",
                "entries": [{
                    "approved_source_id": "p4-live-fy2025-mara-riot",
                    "run_id": SOURCE_RUN_ID,
                    "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
                    "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
                    "packet_sha256": PACKET_FILE_SHA256,
                    "report_sha256": REPORT_SHA256,
                    "raw_sha256": RAW_SHA256,
                }],
            }), encoding="utf-8")
            coordinator = P5Coordinator(
                registry_path=registry_path, approved_run_root=approved_root,
                run_root=private / "p5-runs",
                policy_path=(Path(__file__).resolve().parents[1] / "policies"
                             / "p5_sec_route.v1.json"),
            )
            result = coordinator.run("p4-live-fy2025-mara-riot", "acceptance-live-001")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.handoff_calls, 1)
            self.assertEqual(result.model_cost_minor, 0)
            run_dir = private / "p5-runs" / result.child_run_id
            packet = DataPacket.from_dict(json.loads((run_dir /
                "02-review-sec-evidence.json").read_text(encoding="utf-8")))
            findings = packet.records[0]
            self.assertEqual(findings["status"], "pass")
            self.assertEqual(findings["sample_sums_usd"],
                             {"Revenues": 1554528000, "Assets": 11223666000})
            self.assertEqual(findings["coverage"]["Assets"],
                             {"available": 2, "total": 2})
            self.assertEqual(findings["coverage"]["Revenues"],
                             {"available": 2, "total": 2})
            values = {row["ticker"]: row["facts"] for row in findings["companies"]}
            self.assertEqual(values["MARA"]["Revenues"]["value_usd"], 907093000)
            self.assertEqual(values["RIOT"]["Revenues"]["value_usd"], 647435000)
            self.assertEqual(values["MARA"]["Assets"]["value_usd"], 7286899000)
            self.assertEqual(values["RIOT"]["Assets"]["value_usd"], 3936767000)
            for run_id in (result.parent_run_id, result.child_run_id):
                state = json.loads((private / "p5-runs" / run_id / "run.json")
                                   .read_text(encoding="utf-8"))
                self.assertIs(state["offline"], True)


if __name__ == "__main__":
    unittest.main()
