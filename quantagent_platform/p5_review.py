"""Independent, deterministic audit of the frozen P4 SEC sample."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .contracts import ContractError, parse_aware_timestamp
from .p5_registry import RAW_NAMES, SecEvidence
from .sec_client import SEC_URLS
from .sec_contracts import COHORT_ID, CONCEPTS, FISCAL_END, FISCAL_START, ISSUERS


class IndependentReviewError(ValueError):
    """Frozen SEC evidence differs from the admitted P4 result."""


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IndependentReviewError("frozen SEC JSON has duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IndependentReviewError("frozen SEC JSON has a non-finite number")


def _strict_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IndependentReviewError("frozen SEC response is not strict JSON") from exc
    if not isinstance(value, dict):
        raise IndependentReviewError("frozen SEC response must be an object")
    return value


def _cik(value: Any) -> str:
    if type(value) is int and value >= 0:
        return f"{value:010d}"
    if isinstance(value, str) and value.isdecimal():
        return value.zfill(10)
    raise IndependentReviewError("frozen SEC CIK is invalid")


def _date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise IndependentReviewError(f"{label} is missing")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise IndependentReviewError(f"{label} is invalid") from exc


def _accepted_at(value: Any) -> datetime:
    if not isinstance(value, str):
        raise IndependentReviewError("SEC acceptance time is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IndependentReviewError("SEC acceptance time is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("America/New_York"))
    return parsed.astimezone(timezone.utc)


def _select_submission(
    submissions: dict[str, Any], issuer: dict[str, str], as_of: datetime,
) -> str:
    if _cik(submissions.get("cik")) != issuer["cik"]:
        raise IndependentReviewError("SEC Submissions CIK differs from pinned issuer")
    tickers = submissions.get("tickers")
    if not isinstance(tickers, list) or issuer["ticker"] not in tickers:
        raise IndependentReviewError("SEC Submissions ticker differs from pinned issuer")
    filings = submissions.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        raise IndependentReviewError("SEC Submissions recent filings are missing")
    accessions = recent.get("accessionNumber")
    if not isinstance(accessions, list):
        raise IndependentReviewError("SEC accession list is missing")
    indices = [i for i, value in enumerate(accessions)
               if value == issuer["accession"]]
    if len(indices) != 1:
        raise IndependentReviewError("pinned SEC accession must appear once")
    position = indices[0]
    try:
        form = recent["form"][position]
        fiscal_end = recent["reportDate"][position]
        accepted = recent["acceptanceDateTime"][position]
    except (KeyError, IndexError, TypeError) as exc:
        raise IndependentReviewError("pinned SEC filing metadata is incomplete") from exc
    if form != "10-K" or fiscal_end != FISCAL_END:
        raise IndependentReviewError("pinned SEC form or fiscal year differs")
    accepted_at = _accepted_at(accepted)
    if accepted_at > as_of:
        raise IndependentReviewError("pinned SEC filing was accepted after as_of")
    return accepted_at.isoformat()


def _select_concept(
    companyfacts: dict[str, Any], issuer: dict[str, str],
    concept: str, as_of: datetime,
) -> dict[str, Any] | None:
    facts = companyfacts.get("facts")
    gaap = facts.get("us-gaap") if isinstance(facts, dict) else None
    if not isinstance(gaap, dict):
        raise IndependentReviewError("SEC Company Facts us-gaap is missing")
    tag = gaap.get(concept)
    if tag is None:
        return None
    units = tag.get("units") if isinstance(tag, dict) else None
    if not isinstance(units, dict):
        raise IndependentReviewError("SEC concept units are invalid")
    rows = units.get("USD")
    if rows is None:
        return None
    if not isinstance(rows, list):
        raise IndependentReviewError("SEC USD facts are invalid")
    selected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise IndependentReviewError("SEC fact row is invalid")
        if row.get("accn") != issuer["accession"] or row.get("form") != "10-K":
            continue
        if row.get("end") != FISCAL_END:
            continue
        if concept == "Revenues" and row.get("start") != FISCAL_START:
            continue
        if concept == "Assets" and row.get("start") not in (None, ""):
            continue
        filed = _date(row.get("filed"), "SEC fact filed date")
        if filed > as_of.date():
            raise IndependentReviewError("SEC fact was filed after as_of")
        amount = row.get("val")
        if type(amount) is not int:
            raise IndependentReviewError("SEC approved fact must be integer USD")
        start = FISCAL_START if concept == "Revenues" else None
        companyfacts_url = next(
            url for kind, cik, url in SEC_URLS
            if kind == "companyfacts" and cik == issuer["cik"]
        )
        evidence_start = start if start is not None else "instant"
        selected.append({
            "evidence_id": (
                f"sec:{issuer['cik']}:{issuer['accession']}:{concept}:"
                f"{evidence_start}:{FISCAL_END}:USD"
            ),
            "concept": concept,
            "unit": "USD",
            "period_start": start,
            "period_end": FISCAL_END,
            "value_usd": amount,
            "filed_at": filed.isoformat(),
            "filing_index_url": issuer["filing_index_url"],
            "companyfacts_url": companyfacts_url,
        })
    if len(selected) > 1:
        raise IndependentReviewError("duplicate qualifying SEC fact")
    return selected[0] if selected else None


def select_issuer_facts(
    submissions_raw: bytes, companyfacts_raw: bytes,
    issuer: dict[str, str], as_of: datetime,
) -> dict[str, Any]:
    """Reselect pinned facts from raw responses without P4 normalization code."""
    if as_of.tzinfo is None:
        raise IndependentReviewError("review as_of must include a timezone")
    submissions = _strict_object(submissions_raw)
    companyfacts = _strict_object(companyfacts_raw)
    accepted_at = _select_submission(submissions, issuer, as_of)
    if _cik(companyfacts.get("cik")) != issuer["cik"]:
        raise IndependentReviewError("SEC Company Facts CIK differs from pinned issuer")
    selected: dict[str, dict[str, Any] | None] = {}
    omissions: dict[str, str] = {}
    for concept in CONCEPTS:
        fact = _select_concept(companyfacts, issuer, concept, as_of)
        selected[concept] = fact
        if fact is None:
            omissions[concept] = "missing_approved_fact"
    return {
        "cik": issuer["cik"],
        "ticker": issuer["ticker"],
        "accession": issuer["accession"],
        "accepted_at": accepted_at,
        "facts": selected,
        "omissions": omissions,
    }


def _assert_equal(actual: Any, expected: Any, label: str) -> None:
    if actual != expected:
        raise IndependentReviewError(f"{label} differs from frozen SEC evidence")


def review_evidence(
    evidence: SecEvidence, bundle: dict[str, object],
) -> dict[str, object]:
    if not isinstance(bundle, dict) or set(bundle) != {
        "cohort_id", "as_of", "sources", "companies", "sector", "peers",
        "report_sha256", "packet_file_sha256", "raw_sha256",
    }:
        raise IndependentReviewError("SEC evidence bundle has invalid fields")
    record = evidence.packet.records[0]
    if record["cohort_id"] != COHORT_ID:
        raise IndependentReviewError("SEC cohort differs from pinned sample")
    for key in ("cohort_id", "as_of", "sources", "companies"):
        _assert_equal(bundle[key], record[key], f"bundle {key}")
    _assert_equal(bundle["packet_file_sha256"], evidence.packet_file_sha256,
                  "bundle packet file hash")
    _assert_equal(bundle["raw_sha256"], evidence.raw_sha256, "bundle raw hashes")
    _assert_equal(bundle["report_sha256"], evidence.report_sha256,
                  "bundle report hash")
    if _sha256(evidence.report) != evidence.report_sha256:
        raise IndependentReviewError("P4 report bytes differ from pinned hash")
    try:
        as_of = parse_aware_timestamp(record["as_of"], "as_of")
    except ContractError as exc:
        raise IndependentReviewError("SEC as_of is invalid") from exc

    companies: list[dict[str, Any]] = []
    for index, issuer in enumerate(ISSUERS):
        first, second = RAW_NAMES[index * 2:index * 2 + 2]
        for raw_name, source_index in ((first, index * 2), (second, index * 2 + 1)):
            raw = evidence.raw.get(raw_name)
            if not isinstance(raw, bytes):
                raise IndependentReviewError("frozen SEC response is missing")
            digest = _sha256(raw)
            if digest != evidence.raw_sha256.get(raw_name):
                raise IndependentReviewError("frozen SEC response hash differs")
            kind, cik, url = SEC_URLS[source_index]
            source = record["sources"][source_index]
            if (source["kind"], source["cik"], source["url"], source["sha256"]) != (
                kind, cik, url, digest
            ):
                raise IndependentReviewError("frozen SEC source identity differs")
        selected = select_issuer_facts(
            evidence.raw[first], evidence.raw[second], issuer, as_of
        )
        admitted = record["companies"][index]
        for key in ("cik", "ticker", "accession", "accepted_at"):
            _assert_equal(admitted[key], selected[key], f"{issuer['ticker']} {key}")
        _assert_equal(admitted["form"], "10-K", "admitted filing form")
        _assert_equal(admitted["fiscal_start"], FISCAL_START, "admitted fiscal start")
        _assert_equal(admitted["fiscal_end"], FISCAL_END, "admitted fiscal end")
        for concept in CONCEPTS:
            actual = admitted["facts"].get(concept)
            expected = selected["facts"][concept]
            _assert_equal(actual, expected, f"{issuer['ticker']} {concept}")
            if expected is None:
                _assert_equal(
                    admitted["omissions"].get(concept), "missing_approved_fact",
                    f"{issuer['ticker']} {concept} omission",
                )
            elif concept in admitted["omissions"]:
                raise IndependentReviewError("admitted fact also marked missing")
        companies.append(selected)

    coverage: dict[str, dict[str, int]] = {}
    sums: dict[str, int | None] = {}
    for concept in CONCEPTS:
        values = [company["facts"][concept]["value_usd"] for company in companies
                  if company["facts"][concept] is not None]
        coverage[concept] = {"available": len(values), "total": len(ISSUERS)}
        sums[concept] = sum(values) if values else None

    sector = evidence.sector_packet.records[0]
    peers = evidence.peer_packet.records[0]
    _assert_equal(bundle["sector"], sector, "P4 sector bundle")
    _assert_equal(bundle["peers"], peers, "P4 peer bundle")
    _assert_equal(sector["coverage"], coverage, "P4 coverage")
    _assert_equal(sector["sample_sums_usd"], sums, "P4 sample sums")
    _assert_equal(sector["companies"], record["companies"], "P4 sector facts")
    _assert_equal(peers["sector"], sector, "P4 peer sector")
    peer_rows = peers["rows"]
    if not isinstance(peer_rows, list) or len(peer_rows) != len(ISSUERS):
        raise IndependentReviewError("P4 peer rows have wrong shape")
    omissions: list[dict[str, str]] = []
    for peer, company in zip(peer_rows, companies):
        for key in ("cik", "ticker", "accession"):
            _assert_equal(peer[key], company[key], f"peer {key}")
        for concept in CONCEPTS:
            fact = company["facts"][concept]
            if fact is None:
                _assert_equal(peer[concept], None, "P4 missing peer fact")
                omissions.append({
                    "ticker": company["ticker"],
                    "concept": concept,
                    "reason": "missing_approved_fact",
                })
            else:
                expected = {
                    **fact,
                    "display_usd_millions": format(
                        Decimal(fact["value_usd"]) / Decimal(1_000_000), "f"
                    ),
                }
                _assert_equal(peer[concept], expected, f"P4 peer {concept}")
    _assert_equal(peers["omissions"], omissions, "P4 peer omissions")
    findings: dict[str, object] = {
        "cohort_id": COHORT_ID,
        "as_of": record["as_of"],
        "status": "unknown" if omissions else "pass",
        "coverage": coverage,
        "sample_sums_usd": sums,
        "companies": companies,
        "source_sha256": dict(evidence.raw_sha256),
        "report_sha256": evidence.report_sha256,
        "methods_checked": [
            "pinned_submissions_accession_form_acceptance",
            "pinned_companyfacts_concept_period_unit",
            "integer_usd_coverage_sum_decimal_display",
            "fixed_p4_report_numeric_tables_and_scope",
        ],
    }
    verify_p4_report(evidence.report, findings)
    return findings


def verify_p4_report(report: bytes, findings: dict[str, object]) -> None:
    try:
        content = report.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IndependentReviewError("P4 report is not UTF-8") from exc
    if _sha256(report) != findings["report_sha256"]:
        raise IndependentReviewError("P4 report hash differs")
    fixed_lines = (
        "- Scope: MARA and Riot FY2025 public filings; this is a two-issuer sample.",
        "Sample sums cover only admitted issuers; they are not industry totals.",
        "- Current SEC Company Facts retrieval is not a historical point-in-time feed.",
    )
    if any(line not in content.splitlines() for line in fixed_lines):
        raise IndependentReviewError("P4 report scope statement differs")
    try:
        sector_text = content.split("## Sector overview", 1)[1].split(
            "## Peer comparison", 1)[0]
        peer_text = content.split("## Peer comparison", 1)[1].split(
            "## Missing or excluded metrics", 1)[0]
    except IndexError as exc:
        raise IndependentReviewError("P4 report fixed sections are missing") from exc
    expected_sector: list[str] = []
    for concept in CONCEPTS:
        coverage = findings["coverage"][concept]
        value = findings["sample_sums_usd"][concept]
        value_text = f"{value:,}" if value is not None else "unavailable"
        expected_sector.append(
            f"| `us-gaap:{concept}` | {coverage['available']}/{coverage['total']} | "
            f"{value_text} |"
        )
    actual_sector = [line for line in sector_text.splitlines()
                     if line.startswith("| `us-gaap:")]
    if actual_sector != expected_sector:
        raise IndependentReviewError("P4 report sector numeric table differs")
    expected_peers: list[str] = []
    for company in findings["companies"]:
        for concept in CONCEPTS:
            fact = company["facts"][concept]
            if fact is None:
                continue
            period = (
                f"{fact['period_start']} to {fact['period_end']}"
                if fact["period_start"] else f"at {fact['period_end']}"
            )
            millions = format(Decimal(fact["value_usd"]) / Decimal(1_000_000), "f")
            links = (
                f"[10-K]({fact['filing_index_url']}); "
                f"[Company Facts]({fact['companyfacts_url']})"
            )
            expected_peers.append(
                f"| {company['ticker']} | `us-gaap:{concept}` | {period} | "
                f"{fact['value_usd']:,} | {millions} | "
                f"`{fact['evidence_id']}` | {links} |"
            )
    actual_peers = [line for line in peer_text.splitlines()
                    if line.startswith("| MARA |") or line.startswith("| RIOT |")]
    if actual_peers != expected_peers:
        raise IndependentReviewError("P4 report peer numeric table differs")


def _markdown(value: Any) -> str:
    result = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in ("\\", "\r", "\n", "|", "`", "*", "[", "]", "(", ")", "#", "!"):
        result = result.replace(character, " " if character in ("\r", "\n") else f"\\{character}")
    return result


def render_review_report(findings: dict[str, object], reviewed_at: str) -> bytes:
    try:
        review_time = parse_aware_timestamp(reviewed_at, "reviewed_at")
        source_time = parse_aware_timestamp(findings["as_of"], "as_of")
    except (ContractError, KeyError, TypeError) as exc:
        raise IndependentReviewError("review timestamps are invalid") from exc
    if review_time < source_time:
        raise IndependentReviewError("review time precedes P4 research as_of")
    lines = [
        "# Independent SEC evidence review",
        "",
        f"- P4 research as of: `{_markdown(findings['as_of'])}`",
        f"- Independent review at: `{_markdown(reviewed_at)}`",
        f"- Result: `{_markdown(findings['status'])}`",
        "- Scope: MARA and Riot FY2025 public filings; this is a two-issuer sample.",
        "",
        "## Independently selected facts",
        "",
        "| Issuer | Metric | Original USD | Evidence |",
        "| --- | --- | ---: | --- |",
    ]
    for company in findings["companies"]:
        for concept in CONCEPTS:
            fact = company["facts"][concept]
            value = f"{fact['value_usd']:,}" if fact is not None else "unknown"
            evidence_id = fact["evidence_id"] if fact is not None else "missing_approved_fact"
            lines.append(
                f"| {_markdown(company['ticker'])} | `us-gaap:{concept}` | {value} | "
                f"`{_markdown(evidence_id)}` |"
            )
    lines.extend(["", "## Sample coverage and sums", "",
                  "| Metric | Coverage | Two-company sum (USD) |",
                  "| --- | ---: | ---: |"])
    for concept in CONCEPTS:
        coverage = findings["coverage"][concept]
        total = findings["sample_sums_usd"][concept]
        total_text = f"{total:,}" if total is not None else "unknown"
        lines.append(
            f"| `us-gaap:{concept}` | {coverage['available']}/{coverage['total']} | "
            f"{total_text} |"
        )
    lines.extend([
        "",
        "## Limits",
        "",
        "- Sample sums are not industry totals or investment advice.",
        "- The frozen SEC retrieval is an observed snapshot, not a historical point-in-time feed.",
        "- Fixed P4 numeric tables and scope were checked; arbitrary prose was not semantically verified.",
        "",
    ])
    return "\n".join(lines).encode("utf-8")
