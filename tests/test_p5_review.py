"""Independent review against frozen SEC bytes and the fixed P4 report."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from quantagent_platform.p5_registry import ApprovedRunRegistry, read_approved_source
from quantagent_platform.p5_review import (
    IndependentReviewError,
    render_review_report,
    review_evidence,
    select_issuer_facts,
    verify_p4_report,
)
from quantagent_platform.runner import RecipeRunner, default_registry
from quantagent_platform.sec_contracts import ISSUERS
from tests.test_sec_contracts import make_payloads, make_responses


ROOT = Path(__file__).resolve().parents[1]
RAW_NAMES = (
    "sec-mara-submissions.json",
    "sec-mara-companyfacts.json",
    "sec-riot-submissions.json",
    "sec-riot-companyfacts.json",
)


class IndependentReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        self.payloads = make_payloads()
        self._build(self.payloads)

    def _build(self, payloads) -> None:
        responses = make_responses(payloads)
        recipe = RecipeRunner.load_recipe(ROOT / "recipes" / "sec_industry_peers.json")
        with patch.dict(os.environ, {"SEC_USER_AGENT": "QuantAgent test@example.invalid"}):
            with patch("quantagent_platform.sec_plugins.fetch_sample",
                       return_value=responses):
                result = RecipeRunner(default_registry()).run(
                    recipe,
                    params={"source_path": "", "report_title": "Synthetic SEC sample"},
                    output_dir=self.runs,
                    allowed_read_roots=[],
                    allowed_permissions={"filesystem:write", "network:https"},
                    offline=False,
                    run_id="synthetic-p4",
                )
        run = result.run_dir
        self.registry_path = self.root / "approved.json"
        entry = {
            "approved_source_id": "synthetic-p4",
            "run_id": result.run_id,
            "recipe": {"id": "sec-industry-peers", "version": "1.0.0"},
            "source_plugin": {"id": "builtin.sec-edgar-source", "version": "1.0.0"},
            "packet_sha256": hashlib.sha256(
                (run / "01-load-sec-facts.json").read_bytes()).hexdigest(),
            "report_sha256": hashlib.sha256(
                (run / "sec_industry_peers.md").read_bytes()).hexdigest(),
            "raw_sha256": {
                name: hashlib.sha256((run / name).read_bytes()).hexdigest()
                for name in RAW_NAMES
            },
        }
        self.registry_path.write_text(
            json.dumps({"registry_version": "quantagent.sec_approved_run.v1",
                        "entries": [entry]}), encoding="utf-8")
        source = ApprovedRunRegistry.load(self.registry_path, self.runs).resolve(
            "synthetic-p4")
        self.evidence = read_approved_source(source)
        record = self.evidence.packet.records[0]
        self.bundle = {
            "cohort_id": record["cohort_id"],
            "as_of": record["as_of"],
            "sources": copy.deepcopy(record["sources"]),
            "companies": copy.deepcopy(record["companies"]),
            "sector": copy.deepcopy(self.evidence.sector_packet.records[0]),
            "peers": copy.deepcopy(self.evidence.peer_packet.records[0]),
            "report_sha256": self.evidence.report_sha256,
            "packet_file_sha256": self.evidence.packet_file_sha256,
            "raw_sha256": dict(self.evidence.raw_sha256),
        }

    def test_recomputes_issuer_values_and_two_company_totals(self) -> None:
        findings = review_evidence(self.evidence, self.bundle)
        self.assertEqual(findings["status"], "pass")
        self.assertEqual(findings["coverage"]["Revenues"],
                         {"available": 2, "total": 2})
        self.assertEqual(findings["coverage"]["Assets"],
                         {"available": 2, "total": 2})
        self.assertEqual(findings["sample_sums_usd"],
                         {"Revenues": 1554528000, "Assets": 11223666000})
        self.assertEqual(findings["companies"][0]["facts"]["Revenues"]["value_usd"],
                         907093000)
        self.assertEqual(findings["companies"][1]["facts"]["Assets"]["value_usd"],
                         3936767000)
        reviewed_at = (
            datetime.fromisoformat(findings["as_of"]) + timedelta(minutes=1)
        ).isoformat()
        report = render_review_report(findings, reviewed_at)
        self.assertIn(findings["as_of"].encode(), report)
        self.assertIn(reviewed_at.encode(), report)
        self.assertIn(b"two-issuer sample", report)

    def test_rejects_wrong_p4_derived_value_with_raw_bytes_unchanged(self) -> None:
        changed = copy.deepcopy(self.bundle)
        changed["peers"]["rows"][0]["Revenues"]["value_usd"] += 1
        with self.assertRaises(IndependentReviewError):
            review_evidence(self.evidence, changed)

    def test_rejects_changed_report_numeric_table_and_scope(self) -> None:
        from dataclasses import replace

        altered = self.evidence.report.replace(b"1,554,528,000", b"1,554,528,001")
        with self.assertRaises(IndependentReviewError):
            review_evidence(replace(self.evidence, report=altered), self.bundle)
        altered = self.evidence.report.replace(
            b"this is a two-issuer sample", b"this is an industry total")
        with self.assertRaises(IndependentReviewError):
            review_evidence(replace(self.evidence, report=altered), self.bundle)

    def test_missing_approved_fact_is_unknown_not_zero(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "runs"
        payloads = make_payloads()
        del payloads[("companyfacts", ISSUERS[0]["cik"])]["facts"]["us-gaap"]["Revenues"]
        self._build(payloads)
        findings = review_evidence(self.evidence, self.bundle)
        self.assertEqual(findings["status"], "unknown")
        self.assertEqual(findings["coverage"]["Revenues"],
                         {"available": 1, "total": 2})
        self.assertIsNone(findings["companies"][0]["facts"]["Revenues"])
        self.assertEqual(findings["companies"][0]["omissions"]["Revenues"],
                         "missing_approved_fact")

    def test_raw_selector_rejects_wrong_identity_form_and_duplicates(self) -> None:
        cases = {
            "submissions_cik": lambda p: p.__setitem__("cik", 1),
            "submissions_form": lambda p: p["filings"]["recent"]["form"].__setitem__(0, "8-K"),
            "duplicate_accession": lambda p: p["filings"]["recent"]["accessionNumber"].append(
                ISSUERS[0]["accession"]),
        }
        for label, change in cases.items():
            with self.subTest(label=label):
                submissions = copy.deepcopy(
                    self.payloads[("submissions", ISSUERS[0]["cik"])])
                companyfacts = copy.deepcopy(
                    self.payloads[("companyfacts", ISSUERS[0]["cik"])])
                change(submissions)
                with self.assertRaises(IndependentReviewError):
                    select_issuer_facts(
                        json.dumps(submissions).encode(),
                        json.dumps(companyfacts).encode(),
                        ISSUERS[0],
                        datetime.now(timezone.utc),
                    )

        companyfacts = copy.deepcopy(
            self.payloads[("companyfacts", ISSUERS[0]["cik"])])
        revenue_rows = companyfacts["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
        revenue_rows.append(dict(revenue_rows[0]))
        with self.assertRaises(IndependentReviewError):
            select_issuer_facts(
                json.dumps(self.payloads[("submissions", ISSUERS[0]["cik"])]).encode(),
                json.dumps(companyfacts).encode(),
                ISSUERS[0],
                datetime.now(timezone.utc),
            )

    def test_raw_selector_rejects_duplicate_keys_and_nonfinite_numbers(self) -> None:
        submissions = json.dumps(
            self.payloads[("submissions", ISSUERS[0]["cik"])]).encode()
        companyfacts = json.dumps(
            self.payloads[("companyfacts", ISSUERS[0]["cik"])]).encode()
        with self.assertRaises(IndependentReviewError):
            select_issuer_facts(
                b'{"cik":1,"cik":2}', companyfacts, ISSUERS[0],
                datetime.now(timezone.utc))
        with self.assertRaises(IndependentReviewError):
            select_issuer_facts(
                submissions, companyfacts.replace(b"907093000", b"NaN", 1),
                ISSUERS[0], datetime.now(timezone.utc))

    def test_raw_selector_filters_period_and_unit_and_rejects_late_filing(self) -> None:
        issuer = ISSUERS[0]
        submissions = json.dumps(
            self.payloads[("submissions", issuer["cik"])]).encode()
        original = copy.deepcopy(self.payloads[("companyfacts", issuer["cik"])])
        changed_period = copy.deepcopy(original)
        changed_period["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0][
            "end"] = "2024-12-31"
        selected = select_issuer_facts(
            submissions, json.dumps(changed_period).encode(), issuer,
            datetime.now(timezone.utc))
        self.assertIsNone(selected["facts"]["Revenues"])

        changed_unit = copy.deepcopy(original)
        units = changed_unit["facts"]["us-gaap"]["Revenues"]["units"]
        units["EUR"] = units.pop("USD")
        selected = select_issuer_facts(
            submissions, json.dumps(changed_unit).encode(), issuer,
            datetime.now(timezone.utc))
        self.assertIsNone(selected["facts"]["Revenues"])

        late = copy.deepcopy(original)
        late["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0][
            "filed"] = "2027-01-01"
        with self.assertRaises(IndependentReviewError):
            select_issuer_facts(
                submissions, json.dumps(late).encode(), issuer,
                datetime.now(timezone.utc))

    def test_fixed_report_tables_are_checked_even_with_a_new_matching_hash(self) -> None:
        findings = review_evidence(self.evidence, self.bundle)
        altered = self.evidence.report.replace(
            b"1,554,528,000", b"1,554,528,001")
        changed_findings = {**findings, "report_sha256": hashlib.sha256(
            altered).hexdigest()}
        with self.assertRaisesRegex(IndependentReviewError, "numeric table"):
            verify_p4_report(altered, changed_findings)


if __name__ == "__main__":
    unittest.main()
