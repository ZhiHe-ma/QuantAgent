"""Deterministic arithmetic over the pinned SEC research packet."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from .contracts import ContractError, DataPacket
from .sec_contracts import CONCEPTS, SEC_FACTS_CONTRACT, validate_sec_packet


SECTOR_CONTRACT = "quantagent.sec_sector_overview.v1"
PEER_CONTRACT = "quantagent.sec_peer_comparison.v1"
_LIMITATIONS = [
    "Two-issuer public-filing sample; sample sums are not industry totals.",
    "Current SEC Company Facts retrieval is not a historical point-in-time feed.",
    "Only matching FY2025 USD Revenues and Assets are compared; no net income or operating metrics.",
]


def _summary(record: dict[str, Any]) -> dict[str, Any]:
    coverage: dict[str, dict[str, int]] = {}
    sample_sums: dict[str, int | None] = {}
    for concept in CONCEPTS:
        admitted = [company["facts"][concept]["value_usd"]
                    for company in record["companies"] if concept in company["facts"]]
        coverage[concept] = {"available": len(admitted), "total": len(record["companies"])}
        sample_sums[concept] = sum(admitted) if admitted else None
    return {
        "cohort_id": record["cohort_id"],
        "as_of": record["as_of"],
        "sources": record["sources"],
        "companies": record["companies"],
        "coverage": coverage,
        "sample_sums_usd": sample_sums,
        "method": "pinned_sec_facts_integer_sum_v1",
        "limitations": list(_LIMITATIONS),
    }


def build_sector(packet: DataPacket) -> DataPacket:
    record = validate_sec_packet(packet)
    return DataPacket.create(
        contract_version=SECTOR_CONTRACT,
        packet_type="sec_sector_overview",
        source="builtin.sec-sector-overview",
        records=[_summary(record)],
        created_at=record["as_of"],
    )


def _checked_sector(packet: DataPacket) -> dict[str, Any]:
    packet.validate()
    if (packet.contract_version != SECTOR_CONTRACT or
            packet.packet_type != "sec_sector_overview" or len(packet.records) != 1):
        raise ContractError("peer comparison requires one sector overview")
    summary = packet.records[0]
    if not isinstance(summary, dict):
        raise ContractError("sector summary must be an object")
    try:
        normalized = {
            "cohort_id": summary["cohort_id"],
            "as_of": summary["as_of"],
            "sources": summary["sources"],
            "companies": summary["companies"],
        }
    except KeyError as exc:
        raise ContractError("sector summary lacks normalized SEC provenance") from exc
    source = DataPacket.create(
        contract_version=SEC_FACTS_CONTRACT,
        packet_type="sec_company_facts",
        source="builtin.sec-edgar-source",
        records=[normalized],
        created_at=normalized["as_of"],
    )
    validate_sec_packet(source)
    if summary != _summary(normalized):
        raise ContractError("sector summary differs from admitted SEC facts")
    return summary


def build_peers(packet: DataPacket) -> DataPacket:
    sector = _checked_sector(packet)
    rows: list[dict[str, Any]] = []
    omissions: list[dict[str, str]] = []
    for company in sector["companies"]:
        row: dict[str, Any] = {
            "cik": company["cik"],
            "ticker": company["ticker"],
            "accession": company["accession"],
        }
        for concept in CONCEPTS:
            fact = company["facts"].get(concept)
            if fact is None:
                row[concept] = None
                omissions.append({
                    "ticker": company["ticker"],
                    "concept": concept,
                    "reason": company["omissions"][concept],
                })
            else:
                row[concept] = {
                    **fact,
                    "display_usd_millions": format(
                        Decimal(fact["value_usd"]) / Decimal(1_000_000), "f"
                    ),
                }
        rows.append(row)
    comparison = {
        "sector": sector,
        "rows": rows,
        "omissions": omissions,
        "conversion": "USD millions = integer USD / 1,000,000 (exact decimal)",
        "method": "same_accession_concept_period_unit_v1",
        "limitations": list(_LIMITATIONS),
    }
    return DataPacket.create(
        contract_version=PEER_CONTRACT,
        packet_type="sec_peer_comparison",
        source="builtin.sec-peer-comparison",
        records=[comparison],
        created_at=sector["as_of"],
    )
