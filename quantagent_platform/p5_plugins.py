"""Offline, fixed-route P5 SEC producer and independent reviewer plugins."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import ContractError, DataPacket, utc_now
from .p5_handoff import HandoffError, RoutePolicy, verify_handoff
from .p5_registry import (
    ApprovedRun, ApprovedRunRegistry, ApprovedSourceError,
    bounded_regular_file, read_approved_source, strict_json,
)
from .p5_review import IndependentReviewError, render_review_report, review_evidence
from .plugins import PluginError, PluginManifest, RunContext


APPROVED = "quantagent.sec_approved_run.v1"
BUNDLE = "quantagent.sec_evidence_bundle.v1"
HANDOFF = "quantagent.agent_handoff.v1"
REVIEW = "quantagent.sec_independent_review.v1"
REPORT = "quantagent.report.v1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "p5_sec_route.v1.json"


def _string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginError(f"P5 plugin requires {key}")
    return value


class SecApprovedRunSource:
    manifest = PluginManifest(
        plugin_id="builtin.sec-approved-run-source", version="1.0.0",
        capability="source.sec_approved_run", input_contracts=(),
        output_contract=APPROVED, permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is not None or not context.offline:
            raise PluginError("approved SEC source requires first offline step")
        try:
            registry_path = context.assert_read_path(_string(config, "registry_path"))
            run_root = context.assert_read_path(_string(config, "approved_run_root"))
            registry = ApprovedRunRegistry.load(registry_path, run_root)
            source = registry.resolve(_string(config, "approved_source_id"))
            evidence = read_approved_source(source)
            record = evidence.packet.records[0]
            return DataPacket.create(
                contract_version=APPROVED, packet_type="sec_approved_run",
                source=self.manifest.plugin_id,
                records=[{
                    "approved_source_pins": source.to_pins(),
                    "cohort_id": record["cohort_id"],
                    "as_of": record["as_of"],
                    "sources": record["sources"],
                    "companies": record["companies"],
                    "sector": evidence.sector_packet.records[0],
                    "peers": evidence.peer_packet.records[0],
                    "report_sha256": evidence.report_sha256,
                    "packet_file_sha256": evidence.packet_file_sha256,
                    "raw_sha256": evidence.raw_sha256,
                }], created_at=record["as_of"],
            )
        except (ApprovedSourceError, ContractError, KeyError, TypeError) as exc:
            raise PluginError("approved SEC run failed verification") from exc


class SecEvidencePreparer:
    manifest = PluginManifest(
        plugin_id="builtin.sec-evidence-preparer", version="1.0.0",
        capability="research.sec_evidence_bundle", input_contracts=(APPROVED,),
        output_contract=BUNDLE, permissions=frozenset(), retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != APPROVED or len(packet.records) != 1:
            raise PluginError("SEC preparer requires one approved source record")
        try:
            packet.validate()
            row = packet.records[0]
            if set(row) != {
                "approved_source_pins", "cohort_id", "as_of", "sources",
                "companies", "sector", "peers", "report_sha256",
                "packet_file_sha256", "raw_sha256",
            }:
                raise PluginError("approved source record has unexpected fields")
            pins = row["approved_source_pins"]
            if (pins["report_sha256"] != row["report_sha256"]
                    or pins["packet_sha256"] != row["packet_file_sha256"]
                    or pins["raw_sha256"] != row["raw_sha256"]):
                raise PluginError("approved source pins differ from bundle")
            bundle = {key: value for key, value in row.items()
                      if key != "approved_source_pins"}
            return DataPacket.create(
                contract_version=BUNDLE, packet_type="sec_evidence_bundle",
                source=self.manifest.plugin_id, records=[bundle],
                created_at=row["as_of"],
            )
        except (ContractError, KeyError, TypeError) as exc:
            raise PluginError("approved SEC evidence bundle is invalid") from exc


class SecHandoffSource:
    manifest = PluginManifest(
        plugin_id="builtin.sec-handoff-source", version="1.0.0",
        capability="source.sec_agent_handoff", input_contracts=(),
        output_contract=HANDOFF, permissions=frozenset({"filesystem:read"}),
        retry_safe=False,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is not None or not context.offline:
            raise PluginError("SEC handoff source requires first offline step")
        try:
            handoff_path = context.assert_read_path(_string(config, "handoff_path"))
            bundle_path = context.assert_read_path(_string(config, "bundle_path"))
            raw = bounded_regular_file(handoff_path, 16 * 1024)
            policy = RoutePolicy.load(POLICY_PATH)
            handoff = verify_handoff(
                raw, _string(config, "handoff_sha256"), policy,
                datetime.now(timezone.utc),
            )
            bundle_raw = bounded_regular_file(bundle_path, 2 * 1024 * 1024)
            bundle = DataPacket.from_dict(strict_json(bundle_raw))
            expected = handoff.envelope["bundle"]
            if (
                hashlib.sha256(bundle_raw).hexdigest() != expected["file_sha256"]
                or bundle.content_sha256 != expected["records_sha256"]
                or bundle.contract_version != BUNDLE
                or len(bundle.records) != 1
                or bundle.source != "builtin.sec-evidence-preparer"
                or bundle_path.name != "02-prepare-sec-evidence.json"
                or bundle_path.parent.name != handoff.envelope["parent_run_id"]
            ):
                raise PluginError("parent SEC bundle differs from handoff")
            return DataPacket.create(
                contract_version=HANDOFF, packet_type="sec_agent_handoff",
                source=self.manifest.plugin_id,
                records=[{
                    "approved_source_pins": handoff.envelope["source_pins"],
                    "bundle": bundle.records[0],
                    "handoff_sha256": handoff.sha256,
                    "coordinator_id": handoff.envelope["coordinator_id"],
                    "parent_run_id": handoff.envelope["parent_run_id"],
                }],
            )
        except (ApprovedSourceError, HandoffError, ContractError,
                KeyError, TypeError) as exc:
            raise PluginError("SEC handoff or parent bundle failed verification") from exc


class SecIndependentReview:
    manifest = PluginManifest(
        plugin_id="builtin.sec-independent-review", version="1.0.0",
        capability="research.sec_independent_review", input_contracts=(HANDOFF,),
        output_contract=REVIEW, permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != HANDOFF or len(packet.records) != 1:
            raise PluginError("SEC review requires one verified handoff")
        try:
            packet.validate()
            row = packet.records[0]
            if set(row) != {
                "approved_source_pins", "bundle", "handoff_sha256",
                "coordinator_id", "parent_run_id",
            }:
                raise PluginError("verified handoff record has unexpected fields")
            root = context.assert_read_path(_string(config, "approved_run_root"))
            source = ApprovedRun.from_pins(row["approved_source_pins"], root)
            context.assert_read_path(str(source.run_dir))
            findings = review_evidence(read_approved_source(source), row["bundle"])
            findings["handoff_sha256"] = row["handoff_sha256"]
            findings["coordinator_id"] = row["coordinator_id"]
            findings["parent_run_id"] = row["parent_run_id"]
            return DataPacket.create(
                contract_version=REVIEW, packet_type="sec_independent_review",
                source=self.manifest.plugin_id, records=[findings],
                created_at=utc_now(),
            )
        except (ApprovedSourceError, IndependentReviewError, ContractError,
                KeyError, TypeError) as exc:
            raise PluginError("independent SEC review failed") from exc


class MarkdownSecIndependentReview:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-sec-independent-review", version="1.0.0",
        capability="report.sec_independent_review", input_contracts=(REVIEW,),
        output_contract=REPORT, permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None,
            config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != REVIEW or len(packet.records) != 1:
            raise PluginError("SEC report requires one independent review")
        try:
            packet.validate()
            reviewed_at = utc_now()
            content = render_review_report(packet.records[0], reviewed_at)
            path = Path(context.run_dir) / "sec_independent_review.md"
            path.write_bytes(content)
            return DataPacket.create(
                contract_version=REPORT, packet_type="markdown_report",
                source=self.manifest.plugin_id,
                records=[{
                    "path": str(path), "format": "markdown",
                    "input_sha256": packet.content_sha256,
                    "artifact_sha256": hashlib.sha256(content).hexdigest(),
                }], created_at=reviewed_at,
            )
        except (IndependentReviewError, ContractError, OSError) as exc:
            raise PluginError("independent SEC report failed") from exc
