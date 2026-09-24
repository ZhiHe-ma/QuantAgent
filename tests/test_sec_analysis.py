import copy
import unittest
from decimal import Decimal

from quantagent_platform.contracts import ContractError, DataPacket
from quantagent_platform.sec_analysis import (
    PEER_CONTRACT,
    SECTOR_CONTRACT,
    build_peers,
    build_sector,
)
from quantagent_platform.sec_contracts import normalize_sample
from tests.test_sec_contracts import ISSUERS, make_payloads, make_responses


class SecAnalysisTests(unittest.TestCase):
    def test_sample_sums_coverage_and_evidence_are_exact(self):
        packet = normalize_sample(make_responses())

        sector = build_sector(packet)
        self.assertEqual(sector.contract_version, SECTOR_CONTRACT)
        summary = sector.records[0]
        self.assertEqual(summary["sample_sums_usd"], {
            "Revenues": 1554528000, "Assets": 11223666000,
        })
        self.assertEqual(summary["coverage"]["Revenues"], {"available": 2, "total": 2})
        self.assertIn("sample", " ".join(summary["limitations"]).lower())
        self.assertEqual(summary["sources"], packet.records[0]["sources"])

        peers = build_peers(sector)
        self.assertEqual(peers.contract_version, PEER_CONTRACT)
        comparison = peers.records[0]
        self.assertEqual(comparison["sector"], summary)
        self.assertEqual([row["ticker"] for row in comparison["rows"]], ["MARA", "RIOT"])
        mara_revenue = comparison["rows"][0]["Revenues"]
        self.assertEqual(mara_revenue["value_usd"], 907093000)
        self.assertEqual(mara_revenue["display_usd_millions"], "907.093")
        self.assertEqual(Decimal(mara_revenue["display_usd_millions"]),
                         Decimal(907093000) / Decimal(1000000))
        self.assertEqual(mara_revenue["evidence_id"],
                         packet.records[0]["companies"][0]["facts"]["Revenues"]["evidence_id"])
        self.assertEqual(mara_revenue["filing_index_url"],
                         packet.records[0]["companies"][0]["facts"]["Revenues"]["filing_index_url"])
        self.assertNotIn("rank", comparison)

    def test_missing_revenue_is_explicit_and_zero_assets_is_present(self):
        payloads = make_payloads()
        mara = payloads[("companyfacts", ISSUERS[0][0])]["facts"]["us-gaap"]
        del mara["Revenues"]
        mara["Assets"]["units"]["USD"][0]["val"] = 0
        sector = build_sector(normalize_sample(make_responses(payloads)))
        summary = sector.records[0]
        self.assertEqual(summary["coverage"]["Revenues"], {"available": 1, "total": 2})
        self.assertEqual(summary["sample_sums_usd"]["Revenues"], 647435000)
        self.assertEqual(summary["coverage"]["Assets"], {"available": 2, "total": 2})
        self.assertEqual(summary["sample_sums_usd"]["Assets"], 3936767000)

        comparison = build_peers(sector).records[0]
        self.assertIsNone(comparison["rows"][0]["Revenues"])
        self.assertEqual(comparison["rows"][0]["Assets"]["value_usd"], 0)
        self.assertEqual(comparison["rows"][0]["Assets"]["display_usd_millions"], "0")
        self.assertIn({"ticker": "MARA", "concept": "Revenues",
                       "reason": "missing_approved_fact"}, comparison["omissions"])

    def test_wrong_contract_and_forged_summary_are_rejected(self):
        packet = normalize_sample(make_responses())
        wrong = DataPacket.create(contract_version="wrong.v1", packet_type="wrong",
                                  source="test", records=list(packet.records))
        with self.assertRaises(ContractError):
            build_sector(wrong)

        sector = build_sector(packet)
        bad = copy.deepcopy(sector.records[0])
        bad["sample_sums_usd"]["Revenues"] += 1
        forged = DataPacket.create(contract_version=SECTOR_CONTRACT,
                                   packet_type="sec_sector_overview", source="test",
                                   records=[bad])
        with self.assertRaises(ContractError):
            build_peers(forged)


if __name__ == "__main__":
    unittest.main()
