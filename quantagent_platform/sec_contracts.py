"""Pinned SEC issuer and XBRL selection for the P4 research sample."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import ContractError, DataPacket, parse_aware_timestamp
from .sec_client import MAX_RESPONSE_BYTES, SEC_URLS, SecResponse


SEC_FACTS_CONTRACT = "quantagent.sec_company_facts.v1"
COHORT_ID = "us-listed-bitcoin-miners-fy2025-mara-riot-v1"
FISCAL_START = "2025-01-01"
FISCAL_END = "2025-12-31"
CONCEPTS = ("Revenues", "Assets")
ISSUERS = (
    {
        "cik": "0001507605", "ticker": "MARA", "accession": "0001507605-26-000007",
        "filing_index_url": "https://www.sec.gov/Archives/edgar/data/1507605/000150760526000007/0001507605-26-000007-index.htm",
    },
    {
        "cik": "0001167419", "ticker": "RIOT", "accession": "0001104659-26-022322",
        "filing_index_url": "https://www.sec.gov/Archives/edgar/data/1167419/000110465926022322/0001104659-26-022322-index.html",
    },
)
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("SEC JSON contains a duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError("SEC JSON contains a non-finite number")


def _load_response(response: SecResponse) -> dict[str, Any]:
    if not isinstance(response.raw, bytes) or len(response.raw) > MAX_RESPONSE_BYTES:
        raise ContractError("SEC response bytes exceed the allowed shape or size")
    if response.sha256 != hashlib.sha256(response.raw).hexdigest():
        raise ContractError("SEC response SHA-256 does not match its bytes")
    try:
        value = json.loads(response.raw.decode("utf-8"),
                           object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("SEC response is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ContractError("SEC response JSON must be an object")
    return value


def _cik(value: Any) -> str:
    if type(value) is int and value >= 0:
        return f"{value:010d}"
    if isinstance(value, str) and value.isdecimal():
        return value.zfill(10)
    raise ContractError("SEC CIK is invalid")


def _acceptance_at(value: Any) -> str:
    if not isinstance(value, str):
        raise ContractError("SEC filing acceptance time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("SEC filing acceptance time is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(timezone.utc).isoformat()


def _submission(submissions: dict[str, Any], issuer: dict[str, str], as_of: datetime) -> str:
    if _cik(submissions.get("cik")) != issuer["cik"]:
        raise ContractError("SEC Submissions CIK does not match pinned cohort")
    tickers = submissions.get("tickers")
    if not isinstance(tickers, list) or issuer["ticker"] not in tickers:
        raise ContractError("SEC Submissions ticker does not match pinned cohort")
    recent = submissions.get("filings", {}).get("recent")
    if not isinstance(recent, dict):
        raise ContractError("SEC Submissions filings.recent is missing")
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        raise ContractError("SEC Submissions accession list is missing")
    positions = [index for index, value in enumerate(accessions)
                 if value == issuer["accession"]]
    if len(positions) != 1:
        raise ContractError("pinned SEC accession must appear exactly once")
    index = positions[0]
    try:
        form = recent["form"][index]
        report_date = recent["reportDate"][index]
        accepted = recent["acceptanceDateTime"][index]
    except (KeyError, IndexError, TypeError) as exc:
        raise ContractError("pinned SEC filing metadata is incomplete") from exc
    if form != "10-K" or report_date != FISCAL_END:
        raise ContractError("pinned SEC filing form or fiscal year end differs")
    accepted_at = _acceptance_at(accepted)
    if parse_aware_timestamp(accepted_at, "accepted_at") > as_of:
        raise ContractError("pinned SEC filing was accepted after research as_of")
    return accepted_at


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise ContractError(f"{field} is missing")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError(f"{field} is invalid") from exc


def _evidence_id(issuer: dict[str, str], concept: str) -> str:
    start = FISCAL_START if concept == "Revenues" else "instant"
    return f"sec:{issuer['cik']}:{issuer['accession']}:{concept}:{start}:{FISCAL_END}:USD"


def _select_fact(
    companyfacts: dict[str, Any], issuer: dict[str, str], concept: str,
    as_of: datetime, companyfacts_url: str,
) -> dict[str, Any] | None:
    gaap = companyfacts.get("facts", {}).get("us-gaap", {})
    if not isinstance(gaap, dict):
        raise ContractError("SEC Company Facts us-gaap section is invalid")
    tag = gaap.get(concept)
    if tag is None:
        return None
    if not isinstance(tag, dict) or not isinstance(tag.get("units"), dict):
        raise ContractError(f"SEC {concept} units are invalid")
    rows = tag["units"].get("USD")
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise ContractError(f"SEC {concept} USD facts are invalid")
    selected = []
    for row in rows:
        if not isinstance(row, dict):
            raise ContractError(f"SEC {concept} fact is not an object")
        if row.get("accn") != issuer["accession"] or row.get("form") != "10-K":
            continue
        if row.get("end") != FISCAL_END:
            continue
        if concept == "Revenues" and row.get("start") != FISCAL_START:
            continue
        if concept == "Assets" and row.get("start") not in (None, ""):
            continue
        filed = _date(row.get("filed"), f"SEC {concept} filed date")
        if filed > as_of.date():
            raise ContractError(f"SEC {concept} was filed after research as_of")
        value = row.get("val")
        if type(value) is not int:
            raise ContractError(f"SEC {concept} value must be integer USD")
        selected.append({
            "evidence_id": _evidence_id(issuer, concept),
            "concept": concept,
            "unit": "USD",
            "period_start": FISCAL_START if concept == "Revenues" else None,
            "period_end": FISCAL_END,
            "value_usd": value,
            "filed_at": filed.isoformat(),
            "filing_index_url": issuer["filing_index_url"],
            "companyfacts_url": companyfacts_url,
        })
    if len(selected) > 1:
        raise ContractError(f"SEC {concept} has duplicate qualifying facts")
    return selected[0] if selected else None


def normalize_sample(responses: list[SecResponse]) -> DataPacket:
    """Select only pinned FY2025 annual facts from four current SEC responses."""
    if not isinstance(responses, list) or len(responses) != len(SEC_URLS):
        raise ContractError("SEC sample requires exactly four responses")
    as_of = datetime.now(timezone.utc)
    source_rows: list[dict[str, str]] = []
    parsed: dict[tuple[str, str], dict[str, Any]] = {}
    for response, (kind, cik, url) in zip(responses, SEC_URLS):
        if (not isinstance(response, SecResponse) or
                (response.kind, response.cik, response.url) != (kind, cik, url)):
            raise ContractError("SEC response identity or URL does not match fixed sample")
        retrieved = parse_aware_timestamp(response.retrieved_at, "retrieved_at")
        if retrieved > as_of:
            raise ContractError("SEC response retrieval is after research as_of")
        parsed[(kind, cik)] = _load_response(response)
        source_rows.append({
            "kind": kind, "cik": cik, "url": url,
            "sha256": response.sha256, "retrieved_at": response.retrieved_at,
        })

    companies = []
    for issuer in ISSUERS:
        cik = issuer["cik"]
        submissions = parsed[("submissions", cik)]
        companyfacts = parsed[("companyfacts", cik)]
        accepted_at = _submission(submissions, issuer, as_of)
        if _cik(companyfacts.get("cik")) != cik:
            raise ContractError("SEC Company Facts CIK does not match pinned cohort")
        companyfacts_url = next(url for kind, source_cik, url in SEC_URLS
                                if kind == "companyfacts" and source_cik == cik)
        facts: dict[str, dict[str, Any]] = {}
        omissions: dict[str, str] = {}
        for concept in CONCEPTS:
            fact = _select_fact(companyfacts, issuer, concept, as_of, companyfacts_url)
            if fact is None:
                omissions[concept] = "missing_approved_fact"
            else:
                facts[concept] = fact
        companies.append({
            "cik": cik, "ticker": issuer["ticker"],
            "accession": issuer["accession"], "form": "10-K",
            "accepted_at": accepted_at,
            "fiscal_start": FISCAL_START, "fiscal_end": FISCAL_END,
            "facts": facts, "omissions": omissions,
        })

    record = {
        "cohort_id": COHORT_ID,
        "as_of": as_of.isoformat(),
        "sources": source_rows,
        "companies": companies,
    }
    packet = DataPacket.create(
        contract_version=SEC_FACTS_CONTRACT,
        packet_type="sec_company_facts",
        source="builtin.sec-edgar-source",
        records=[record],
        created_at=record["as_of"],
    )
    validate_sec_packet(packet)
    return packet


def validate_sec_packet(packet: DataPacket) -> dict[str, Any]:
    """Check the normalized record's semantic contract before transforms/replay."""
    packet.validate()
    if (packet.contract_version != SEC_FACTS_CONTRACT or
            packet.packet_type != "sec_company_facts" or len(packet.records) != 1):
        raise ContractError("expected one normalized SEC Company Facts record")
    record = packet.records[0]
    if set(record) != {"cohort_id", "as_of", "sources", "companies"}:
        raise ContractError("normalized SEC record has an invalid shape")
    if record["cohort_id"] != COHORT_ID:
        raise ContractError("normalized SEC cohort does not match pinned sample")
    as_of = parse_aware_timestamp(record["as_of"], "as_of")
    if as_of > datetime.now(timezone.utc):
        raise ContractError("normalized SEC as_of is in the future")
    sources = record["sources"]
    if not isinstance(sources, list) or len(sources) != len(SEC_URLS):
        raise ContractError("normalized SEC sources must contain four responses")
    for source, (kind, cik, url) in zip(sources, SEC_URLS):
        if not isinstance(source, dict) or set(source) != {
                "kind", "cik", "url", "sha256", "retrieved_at"}:
            raise ContractError("normalized SEC source has an invalid shape")
        if (source["kind"], source["cik"], source["url"]) != (kind, cik, url):
            raise ContractError("normalized SEC source URL or identity is invalid")
        if not isinstance(source["sha256"], str) or not _HEX_64.fullmatch(source["sha256"]):
            raise ContractError("normalized SEC source SHA-256 is invalid")
        if parse_aware_timestamp(source["retrieved_at"], "retrieved_at") > as_of:
            raise ContractError("normalized SEC retrieval exceeds as_of")
    companies = record["companies"]
    if not isinstance(companies, list) or len(companies) != len(ISSUERS):
        raise ContractError("normalized SEC cohort must contain both issuers")
    for company, issuer in zip(companies, ISSUERS):
        if not isinstance(company, dict) or set(company) != {
                "cik", "ticker", "accession", "form", "accepted_at",
                "fiscal_start", "fiscal_end", "facts", "omissions"}:
            raise ContractError("normalized SEC issuer has an invalid shape")
        if (company["cik"], company["ticker"], company["accession"],
                company["form"], company["fiscal_start"], company["fiscal_end"]) != (
                issuer["cik"], issuer["ticker"], issuer["accession"],
                "10-K", FISCAL_START, FISCAL_END):
            raise ContractError("normalized SEC issuer identity or period is invalid")
        if parse_aware_timestamp(company["accepted_at"], "accepted_at") > as_of:
            raise ContractError("normalized SEC acceptance exceeds as_of")
        facts, omissions = company["facts"], company["omissions"]
        if not isinstance(facts, dict) or not isinstance(omissions, dict):
            raise ContractError("normalized SEC facts or omissions are invalid")
        if set(facts) | set(omissions) != set(CONCEPTS) or set(facts) & set(omissions):
            raise ContractError("normalized SEC metric coverage is invalid")
        companyfacts_url = next(url for kind, source_cik, url in SEC_URLS
                                if kind == "companyfacts" and source_cik == issuer["cik"])
        for concept, fact in facts.items():
            if not isinstance(fact, dict) or set(fact) != {
                    "evidence_id", "concept", "unit", "period_start", "period_end",
                    "value_usd", "filed_at", "filing_index_url", "companyfacts_url"}:
                raise ContractError("normalized SEC fact has an invalid shape")
            if (fact["evidence_id"] != _evidence_id(issuer, concept) or
                    fact["concept"] != concept or fact["unit"] != "USD" or
                    fact["period_start"] != (FISCAL_START if concept == "Revenues" else None) or
                    fact["period_end"] != FISCAL_END or
                    fact["filing_index_url"] != issuer["filing_index_url"] or
                    fact["companyfacts_url"] != companyfacts_url or
                    type(fact["value_usd"]) is not int):
                raise ContractError("normalized SEC fact semantics are invalid")
            if _date(fact["filed_at"], "filed_at") > as_of.date():
                raise ContractError("normalized SEC fact filed after as_of")
        if any(reason != "missing_approved_fact" for reason in omissions.values()):
            raise ContractError("normalized SEC omission reason is invalid")
    return record
