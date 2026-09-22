from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .contracts import ContractError, DataPacket
from .plugins import PluginError, PluginManifest, RunContext
from .research_contracts import (
    REPORT_CONTRACT,
    THESIS_REVIEW_INPUT_CONTRACT,
    THESIS_STATE_CONTRACT,
    load_strict_json,
    update_thesis,
    validate_review_fixture,
    validate_thesis_state,
)


def _markdown(value: Any) -> str:
    escaped = (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\\", "\\\\")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    for character in ("`", "|", "*", "[", "]", "(", ")", "#", "!"):
        escaped = escaped.replace(character, f"\\{character}")
    return escaped


class JsonThesisReviewSource:
    manifest = PluginManifest(
        plugin_id="builtin.json-thesis-review-source",
        version="1.0.0",
        capability="source.thesis_review",
        input_contracts=(),
        output_contract=THESIS_REVIEW_INPUT_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(
        self,
        context: RunContext,
        packet: DataPacket | None,
        config: dict[str, Any],
    ) -> DataPacket:
        if packet is not None:
            raise PluginError("thesis review source must be the first recipe step")
        source_path = context.assert_read_path(str(config.get("path", "")))
        try:
            fixture = validate_review_fixture(load_strict_json(source_path))
        except ContractError as exc:
            raise PluginError(str(exc)) from exc
        raw_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
        return DataPacket.create(
            contract_version=THESIS_REVIEW_INPUT_CONTRACT,
            packet_type="thesis_review_input",
            source=self.manifest.plugin_id,
            records=[fixture],
            metadata={
                "source_path": str(source_path),
                "source_sha256": raw_sha256,
                "roles": {
                    "reader": "explicit_fixture_only",
                    "analyst": "packet_only_no_filesystem_or_network",
                    "writer": "current_run_directory_only",
                },
                "untrusted_evidence": True,
            },
        )


class DeterministicThesisTracker:
    manifest = PluginManifest(
        plugin_id="builtin.deterministic-thesis-tracker",
        version="1.0.0",
        capability="research.thesis_update",
        input_contracts=(THESIS_REVIEW_INPUT_CONTRACT,),
        output_contract=THESIS_STATE_CONTRACT,
        permissions=frozenset(),
        retry_safe=True,
    )

    def run(
        self,
        context: RunContext,
        packet: DataPacket | None,
        config: dict[str, Any],
    ) -> DataPacket:
        if (
            packet is None
            or packet.contract_version != THESIS_REVIEW_INPUT_CONTRACT
            or len(packet.records) != 1
        ):
            raise PluginError(
                f"thesis tracker requires one {THESIS_REVIEW_INPUT_CONTRACT} record"
            )
        try:
            state = update_thesis(packet.records[0])
        except ContractError as exc:
            raise PluginError(str(exc)) from exc
        return DataPacket.create(
            contract_version=THESIS_STATE_CONTRACT,
            packet_type="thesis_state",
            source=self.manifest.plugin_id,
            records=[state],
            metadata={
                "input_contract": packet.contract_version,
                "input_sha256": packet.content_sha256,
                "transformation": "deterministic_rule_set_v1",
                "model_used": False,
                "network_used": False,
                "trading_authority": False,
            },
        )


class MarkdownThesisReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-thesis-report",
        version="1.0.0",
        capability="report.thesis",
        input_contracts=(THESIS_STATE_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(
        self,
        context: RunContext,
        packet: DataPacket | None,
        config: dict[str, Any],
    ) -> DataPacket:
        if (
            packet is None
            or packet.contract_version != THESIS_STATE_CONTRACT
            or len(packet.records) != 1
        ):
            raise PluginError(f"thesis report requires one {THESIS_STATE_CONTRACT} record")
        state = packet.records[0]
        try:
            validate_thesis_state(state)
        except ContractError as exc:
            raise PluginError(str(exc)) from exc
        report_name = str(config.get("filename", "thesis_review_report.md"))
        if Path(report_name).name != report_name or not report_name.endswith(".md"):
            raise PluginError("thesis report filename must be a plain .md filename")
        title = _markdown(config.get("title", "QuantAgent 观点跟踪报告"))

        lines = [
            f"# {title}",
            "",
            f"- Thesis: `{_markdown(state['thesis_id'])}` v{state['version']}",
            f"- As of: `{_markdown(state['as_of'])}`",
            f"- Assessment: **{_markdown(state['current_assessment'])}**",
            f"- Research suggestion: **{_markdown(state['research_suggestion'])}**",
            f"- Evidence sufficient: **{str(state['statuses']['evidence_sufficient']).lower()}**",
            f"- Human reviewed: **{str(state['statuses']['human_reviewed']).lower()}**",
            f"- Action eligible: **{str(state['statuses']['action_eligible']).lower()}**",
            "",
            "## Core thesis",
            "",
            _markdown(state["core_thesis"]),
            "",
            "## Claim scorecard",
            "",
            "| Claim | Status | Evidence |",
            "| --- | --- | --- |",
        ]
        for claim in state["claims"]:
            refs = ", ".join(f"`{_markdown(item)}`" for item in claim["evidence_refs"]) or "—"
            lines.append(
                f"| {_markdown(claim['text'])} | `{_markdown(claim['status'])}` | {refs} |"
            )

        lines.extend(
            [
                "",
                "## Evidence index",
                "",
                "Raw excerpts remain untrusted in the input packet and are not rendered here.",
                "",
                "| Evidence | Stance | Impact | Source | Claims | Content SHA-256 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for evidence in state["evidence_index"]:
            claims = ", ".join(f"`{_markdown(item)}`" for item in evidence["claim_refs"])
            lines.append(
                "| "
                f"`{_markdown(evidence['evidence_id'])}` | "
                f"`{_markdown(evidence['stance'])}` | "
                f"`{_markdown(evidence['impact'])}` | "
                f"{_markdown(evidence['source_title'])} | "
                f"{claims} | `{_markdown(evidence['content_sha256'])}` |"
            )

        lines.extend(
            [
                "",
                "## Invalidation conditions",
                "",
                "| Condition | Status | Evidence |",
                "| --- | --- | --- |",
            ]
        )
        for condition in state["invalidation_conditions"]:
            refs = ", ".join(
                f"`{_markdown(item)}`" for item in condition["evidence_refs"]
            ) or "—"
            lines.append(
                f"| {_markdown(condition['text'])} | "
                f"`{_markdown(condition['status'])}` | {refs} |"
            )

        lines.extend(["", "## Missing information", ""])
        lines.extend(
            [f"- `{_markdown(item)}`" for item in state["missing_information"]]
            or ["- None declared by the deterministic checks."]
        )
        lines.extend(
            [
                "",
                "## Revision",
                "",
                f"- Added evidence: {', '.join(state['revision']['added_evidence_refs']) or 'none'}",
                f"- Reasons: {', '.join(state['revision']['reason_codes']) or 'none'}",
                f"- Previous state SHA-256: `{state['lineage']['previous_thesis_sha256']}`",
                f"- Evidence bundle SHA-256: `{state['lineage']['evidence_bundle_sha256']}`",
                "",
                "## Scope",
                "",
                "This deterministic offline report organizes supplied evidence. It does not verify external truth, predict returns, authorize trading, or convert research suggestions into orders.",
                "",
            ]
        )
        content = "\n".join(lines)
        report_path = Path(context.run_dir) / report_name
        report_bytes = content.encode("utf-8")
        try:
            report_path.write_bytes(report_bytes)
        except OSError as exc:
            raise PluginError(f"cannot write thesis report {report_path}: {exc}") from exc
        artifact_sha256 = hashlib.sha256(report_bytes).hexdigest()
        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[
                {
                    "path": str(report_path),
                    "format": "markdown",
                    "input_contract": packet.contract_version,
                    "input_sha256": packet.content_sha256,
                    "artifact_sha256": artifact_sha256,
                    "assessment": state["current_assessment"],
                    "action_eligible": False,
                }
            ],
            metadata={
                "deterministic_content": True,
                "raw_evidence_rendered": False,
                "trading_authority": False,
            },
        )
