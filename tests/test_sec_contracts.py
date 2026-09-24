import copy
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from quantagent_platform.contracts import ContractError, DataPacket
from quantagent_platform.sec_client import SEC_URLS, SecResponse
from quantagent_platform.sec_contracts import (
    COHORT_ID,
    SEC_FACTS_CONTRACT,
    normalize_sample,
    validate_sec_packet,
)


ISSUERS = (
    ("0001507605", "MARA", "0001507605-26-000007", 907093000, 7286899000),
    ("0001167419", "RIOT", "0001104659-26-022322", 647435000, 3936767000),
)


def make_payloads():
    payloads = {}
    for cik, ticker, accession, revenues, assets in ISSUERS:
        submissions = {
            "cik": int(cik),
            "name": ticker + " Test Issuer",
            "tickers": [ticker],
            "filings": {"recent": {
                "accessionNumber": [accession, "0000000000-26-000001"],
                "form": ["10-K", "10-K/A"],
                "reportDate": ["2025-12-31", "2025-12-31"],
                "acceptanceDateTime": ["2026-03-02T16:49:11.000", "2026-04-01T11:00:00.000"],
            }},
        }
        revenue_row = {
            "start": "2025-01-01", "end": "2025-12-31", "val": revenues,
            "accn": accession, "fy": 2025, "fp": "FY", "form": "10-K",
            "filed": "2026-03-02", "frame": "CY2025",
        }
        assets_row = {
            "end": "2025-12-31", "val": assets,
            "accn": accession, "fy": 2025, "fp": "FY", "form": "10-K",
            "filed": "2026-03-02", "frame": "CY2025Q4I",
        }
        amended = {**revenue_row, "val": 999999999, "accn": "0000000000-26-000001",
                   "form": "10-K/A", "filed": "2026-04-01"}
        facts = {"cik": int(cik), "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [revenue_row, amended]}},
            "Assets": {"units": {"USD": [assets_row]}},
            "NetIncomeLoss": {"units": {"USD": [{**revenue_row, "val": 123}]}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {"USD": [{**revenue_row, "val": 58704000}]}
            },
        }}}
        payloads[("submissions", cik)] = submissions
        payloads[("companyfacts", cik)] = facts
    return payloads


def make_responses(payloads=None, *, retrieved_at=None):
    payloads = payloads or make_payloads()
    retrieved_at = retrieved_at or (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    rows = []
    for kind, cik, url in SEC_URLS:
        raw = json.dumps(payloads[(kind, cik)], separators=(",", ":")).encode("utf-8")
        rows.append(SecResponse(kind, cik, url, raw, hashlib.sha256(raw).hexdigest(),
                                retrieved_at))
    return rows


class SecContractsTests(unittest.TestCase):
    def test_selects_pinned_annual_usd_facts_and_keeps_hashed_provenance(self):
        packet = normalize_sample(make_responses())
        self.assertEqual(packet.contract_version, SEC_FACTS_CONTRACT)
        record = validate_sec_packet(packet)
        self.assertEqual(record["cohort_id"], COHORT_ID)
        self.assertEqual(len(record["sources"]), 4)
        self.assertEqual([source["url"] for source in record["sources"]],
                         [url for _, _, url in SEC_URLS])
        self.assertTrue(all(datetime.fromisoformat(record["as_of"]) >=
                            datetime.fromisoformat(source["retrieved_at"])
                            for source in record["sources"]))
        self.assertEqual(len(record["companies"]), 2)
        mara, riot = record["companies"]
        self.assertEqual((mara["cik"], mara["ticker"], mara["accession"]),
                         ISSUERS[0][:3])
        self.assertEqual(mara["facts"]["Revenues"]["value_usd"], 907093000)
        self.assertEqual(riot["facts"]["Assets"]["value_usd"], 3936767000)
        self.assertEqual(set(mara["facts"]), {"Revenues", "Assets"})
        self.assertEqual(mara["facts"]["Revenues"]["unit"], "USD")
        self.assertEqual(mara["facts"]["Revenues"]["period_start"], "2025-01-01")
        self.assertIsNone(mara["facts"]["Assets"]["period_start"])
        self.assertIn("sec.gov/Archives/edgar/data/1507605/", mara["facts"]["Assets"]["filing_index_url"])
        self.assertIn("0001507605-26-000007", mara["facts"]["Revenues"]["evidence_id"])
        self.assertEqual(mara["accepted_at"], "2026-03-02T21:49:11+00:00")

    def test_missing_or_wrong_semantics_are_omitted_but_zero_is_not_missing(self):
        payloads = make_payloads()
        mara_facts = payloads[("companyfacts", ISSUERS[0][0])]["facts"]["us-gaap"]
        del mara_facts["Revenues"]
        riot_facts = payloads[("companyfacts", ISSUERS[1][0])]["facts"]["us-gaap"]
        riot_facts["Revenues"]["units"] = {"EUR": riot_facts["Revenues"]["units"]["USD"]}
        riot_facts["Assets"]["units"]["USD"][0]["val"] = 0

        record = validate_sec_packet(normalize_sample(make_responses(payloads)))

        self.assertNotIn("Revenues", record["companies"][0]["facts"])
        self.assertEqual(record["companies"][0]["omissions"]["Revenues"], "missing_approved_fact")
        self.assertEqual(record["companies"][1]["omissions"]["Revenues"], "missing_approved_fact")
        self.assertEqual(record["companies"][1]["facts"]["Assets"]["value_usd"], 0)

    def test_core_identity_period_and_duplicate_values_fail_closed(self):
        for field in ("cik", "ticker", "report_date", "form", "duplicate", "future_acceptance"):
            with self.subTest(field=field):
                payloads = make_payloads()
                cik = ISSUERS[0][0]
                submission = payloads[("submissions", cik)]
                facts = payloads[("companyfacts", cik)]
                if field == "cik":
                    submission["cik"] = 827876
                    facts["cik"] = 827876
                elif field == "ticker":
                    submission["tickers"] = ["CLSK"]
                elif field == "report_date":
                    submission["filings"]["recent"]["reportDate"][0] = "2025-09-30"
                elif field == "form":
                    submission["filings"]["recent"]["form"][0] = "10-Q"
                elif field == "duplicate":
                    rows = facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
                    rows.append(copy.deepcopy(rows[0]))
                else:
                    submission["filings"]["recent"]["acceptanceDateTime"][0] = "2099-01-01T12:00:00.000"
                with self.assertRaises(ContractError):
                    normalize_sample(make_responses(payloads))

    def test_wrong_period_does_not_replace_admitted_fact(self):
        payloads = make_payloads()
        rows = payloads[("companyfacts", ISSUERS[0][0])]["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        rows[0]["start"] = "2025-10-01"
        record = validate_sec_packet(normalize_sample(make_responses(payloads)))
        self.assertEqual(record["companies"][0]["omissions"]["Revenues"], "missing_approved_fact")

    def test_raw_hash_and_packet_digest_tampering_are_rejected(self):
        responses = make_responses()
        first = responses[0]
        responses[0] = SecResponse(first.kind, first.cik, first.url, first.raw,
                                   "0" * 64, first.retrieved_at)
        with self.assertRaises(ContractError):
            normalize_sample(responses)

        packet = normalize_sample(make_responses())
        tampered = copy.deepcopy(packet.to_dict())
        tampered["records"][0]["sources"][0]["sha256"] = "0" * 64
        with self.assertRaises(ContractError):
            DataPacket.from_dict(tampered)

    def test_recomputed_digest_still_requires_valid_source_url_and_aware_time(self):
        packet = normalize_sample(make_responses())
        for field, value in (("url", "https://example.invalid/x"),
                             ("retrieved_at", "2026-09-24T00:00:00")):
            with self.subTest(field=field):
                record = copy.deepcopy(packet.records[0])
                record["sources"][0][field] = value
                forged = DataPacket.create(contract_version=SEC_FACTS_CONTRACT,
                                           packet_type="sec_company_facts",
                                           source=packet.source, records=[record],
                                           created_at=packet.created_at)
                with self.assertRaises(ContractError):
                    validate_sec_packet(forged)

    def test_new_york_acceptance_timestamp_handles_daylight_saving(self):
        payloads = make_payloads()
        payloads[("submissions", ISSUERS[0][0])]["filings"]["recent"]["acceptanceDateTime"][0] = "2026-03-08T03:30:00.000"
        mara = validate_sec_packet(normalize_sample(make_responses(payloads)))["companies"][0]
        self.assertEqual(mara["accepted_at"], "2026-03-08T07:30:00+00:00")

    def test_rejects_duplicate_json_keys(self):
        responses = make_responses()
        first = responses[0]
        raw = b'{"cik":1507605,"cik":1507605}'
        responses[0] = SecResponse(first.kind, first.cik, first.url, raw,
                                   hashlib.sha256(raw).hexdigest(), first.retrieved_at)
        with self.assertRaises(ContractError):
            normalize_sample(responses)


if __name__ == "__main__":
    unittest.main()
