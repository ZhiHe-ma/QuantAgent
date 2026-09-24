"""SEC source, deterministic research, and Markdown recipe plugins."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .contracts import ContractError, DataPacket
from .plugins import PluginError, PluginManifest, RunContext
from .sec_analysis import PEER_CONTRACT, SECTOR_CONTRACT, build_peers, build_sector
from .sec_client import fetch_sample
from .sec_contracts import SEC_FACTS_CONTRACT, validate_sec_packet, normalize_sample


REPORT_CONTRACT = "quantagent.report.v1"
_RAW_NAMES = (
    "sec-mara-submissions.json",
    "sec-mara-companyfacts.json",
    "sec-riot-submissions.json",
    "sec-riot-companyfacts.json",
)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("replay packet JSON contains duplicate keys")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ContractError("replay packet JSON contains a non-finite number")


def _markdown(value: Any) -> str:
    result = (str(value).replace("&", "&amp;").replace("<", "&lt;")
              .replace(">", "&gt;").replace("\\", "\\\\")
              .replace("\r", " ").replace("\n", " "))
    for character in ("`", "|", "*", "[", "]", "(", ")", "#", "!"):
        result = result.replace(character, f"\\{character}")
    return result


class SecEdgarSource:
    manifest = PluginManifest(
        plugin_id="builtin.sec-edgar-source",
        version="1.0.0",
        capability="source.sec_company_facts",
        input_contracts=(),
        output_contract=SEC_FACTS_CONTRACT,
        permissions=frozenset({"network:https", "filesystem:write"}),
        network_access=True,
        retry_safe=False,
        catalog_status="experimental",
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is not None or context.offline:
            raise PluginError("SEC live source requires the first step in online mode")
        contact = os.environ.get("SEC_USER_AGENT", "")
        if not contact.strip():
            raise PluginError("SEC_USER_AGENT with a project contact is required")
        responses = fetch_sample(contact)
        try:
            normalized = normalize_sample(responses)
        except ContractError as exc:
            raise PluginError(str(exc)) from exc
        contact_tokens = [contact, *re.findall(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", contact)]
        if any(token.encode("utf-8") in response.raw
               for response in responses for token in contact_tokens):
            raise PluginError("SEC response unexpectedly contains the project contact")
        for response, name in zip(responses, _RAW_NAMES):
            try:
                (Path(context.run_dir) / name).write_bytes(response.raw)
            except OSError:
                raise PluginError("cannot save SEC response in current run directory") from None
        return normalized


class SecReplaySource:
    manifest = PluginManifest(
        plugin_id="builtin.sec-replay-source",
        version="1.0.0",
        capability="source.sec_company_facts",
        input_contracts=(),
        output_contract=SEC_FACTS_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("SEC replay source must be the first step")
        if not isinstance(config.get("path"), str) or not config["path"]:
            raise PluginError("SEC replay source requires config.path")
        path = context.assert_read_path(config["path"])
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise PluginError("SEC replay packet exceeds 2 MiB limit")
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs,
                               parse_constant=_reject_constant)
            original = DataPacket.from_dict(value)
            validate_sec_packet(original)
        except PluginError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ContractError,
                TypeError, ValueError):
            raise PluginError("SEC replay packet failed validation") from None
        return DataPacket.create(
            contract_version=SEC_FACTS_CONTRACT,
            packet_type="sec_company_facts",
            source=self.manifest.plugin_id,
            records=list(original.records),
            created_at=original.created_at,
        )


class SecSectorOverview:
    manifest = PluginManifest(
        plugin_id="builtin.sec-sector-overview",
        version="1.0.0",
        capability="research.sec_sector_overview",
        input_contracts=(SEC_FACTS_CONTRACT,),
        output_contract=SECTOR_CONTRACT,
        permissions=frozenset(),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None:
            raise PluginError("SEC sector overview requires a normalized packet")
        try:
            return build_sector(packet)
        except ContractError as exc:
            raise PluginError(str(exc)) from exc


class SecPeerComparison:
    manifest = PluginManifest(
        plugin_id="builtin.sec-peer-comparison",
        version="1.0.0",
        capability="research.sec_peer_comparison",
        input_contracts=(SECTOR_CONTRACT,),
        output_contract=PEER_CONTRACT,
        permissions=frozenset(),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None:
            raise PluginError("SEC peer comparison requires a sector packet")
        try:
            return build_peers(packet)
        except ContractError as exc:
            raise PluginError(str(exc)) from exc


class MarkdownSecResearchReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-sec-research-report",
        version="1.0.0",
        capability="report.sec_research",
        input_contracts=(PEER_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != PEER_CONTRACT or len(packet.records) != 1:
            raise PluginError("SEC report requires one peer comparison")
        try:
            packet.validate()
            comparison = packet.records[0]
            sector = comparison["sector"]
            rebuilt = build_peers(DataPacket.create(
                contract_version=SECTOR_CONTRACT,
                packet_type="sec_sector_overview",
                source="builtin.sec-sector-overview",
                records=[sector],
                created_at=sector["as_of"],
            ))
            if comparison != rebuilt.records[0]:
                raise ContractError("SEC peer comparison differs from admitted facts")
        except (ContractError, KeyError, TypeError) as exc:
            raise PluginError("SEC report input failed semantic validation") from exc
        title = _markdown(config.get("title", "SEC mining issuer sample"))
        lines = [
            f"# {title}", "",
            f"- Cohort: `{_markdown(sector['cohort_id'])}`",
            f"- Research as of: `{_markdown(sector['as_of'])}`",
            "- Scope: MARA and Riot FY2025 public filings; this is a two-issuer sample.",
            "- Availability: filing acceptance is an event time; retrieval is this run's observed time, not first public availability.",
            "", "## Method", "",
            "Only the same `us-gaap:Revenues` annual duration and `us-gaap:Assets` year-end instant in integer USD are admitted.",
            "USD millions = original integer USD / 1,000,000 exactly. No quarterly annualization or inferred operating metrics.",
            "", "## Sector overview", "",
            "Sample sums cover only admitted issuers; they are not industry totals.",
            "", "| Metric | Coverage | Sample sum (USD) |", "| --- | ---: | ---: |",
        ]
        for concept in ("Revenues", "Assets"):
            coverage = sector["coverage"][concept]
            value = sector["sample_sums_usd"][concept]
            value_text = f"{value:,}" if value is not None else "unavailable"
            lines.append(f"| `us-gaap:{concept}` | {coverage['available']}/{coverage['total']} | {value_text} |")
        lines.extend([
            "", "## Peer comparison", "",
            "| Issuer | Metric | Fiscal period | Original USD | USD millions | Evidence | Sources |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ])
        for row in comparison["rows"]:
            for concept in ("Revenues", "Assets"):
                fact = row[concept]
                if fact is None:
                    continue
                period = (f"{fact['period_start']} to {fact['period_end']}" if fact["period_start"]
                          else f"at {fact['period_end']}")
                links = (f"[10-K]({fact['filing_index_url']}); "
                         f"[Company Facts]({fact['companyfacts_url']})")
                lines.append(
                    f"| {_markdown(row['ticker'])} | `us-gaap:{concept}` | {period} | "
                    f"{fact['value_usd']:,} | {fact['display_usd_millions']} | "
                    f"`{_markdown(fact['evidence_id'])}` | {links} |"
                )
        lines.extend([
            "", "## Missing or excluded metrics", "",
            "| Issuer | Metric | Reason |", "| --- | --- | --- |",
        ])
        if comparison["omissions"]:
            for omission in comparison["omissions"]:
                lines.append(f"| {_markdown(omission['ticker'])} | `{_markdown(omission['concept'])}` | `{_markdown(omission['reason'])}` |")
        else:
            lines.append("| Both | Approved metrics | None |")
        lines.extend([
            "| Both | `ProfitLoss` / `NetIncomeLoss` | Different issuer presentation; excluded from numeric comparison |",
            "| Both | `RevenueFromContractWithCustomerExcludingAssessedTax` | Narrower subtotal; does not replace total Revenues |",
            "", "## Provenance", "",
            "| Issuer | 10-K accession | Accepted at (UTC) |",
            "| --- | --- | --- |",
        ])
        for company in sector["companies"]:
            lines.append(f"| {_markdown(company['ticker'])} | `{_markdown(company['accession'])}` | `{_markdown(company['accepted_at'])}` |")
        lines.extend([
            "", "| SEC JSON response | CIK | Retrieved at (UTC) | SHA-256 |",
            "| --- | --- | --- | --- |",
        ])
        for source in sector["sources"]:
            lines.append(f"| [{_markdown(source['kind'])}]({source['url']}) | `{source['cik']}` | `{_markdown(source['retrieved_at'])}` | `{source['sha256']}` |")
        lines.extend(["", "## Limitations", ""])
        lines.extend(f"- {_markdown(item)}" for item in comparison["limitations"])
        lines.append("")

        report_path = Path(context.run_dir) / "sec_industry_peers.md"
        content = "\n".join(lines).encode("utf-8")
        try:
            report_path.write_bytes(content)
        except OSError:
            raise PluginError("cannot write SEC report in current run directory") from None
        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[{
                "path": str(report_path), "format": "markdown",
                "input_sha256": packet.content_sha256,
                "artifact_sha256": hashlib.sha256(content).hexdigest(),
            }],
            created_at=sector["as_of"],
        )
