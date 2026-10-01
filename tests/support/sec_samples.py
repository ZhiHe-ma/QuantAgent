"""Shared synthetic SEC fixtures; preserved from the original contract tests."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from quantagent_platform.sec_client import SEC_URLS, SecResponse


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


