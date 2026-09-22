from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from .contracts import ContractError, parse_aware_timestamp, sha256_json


RESEARCH_REQUEST_CONTRACT = "quantagent.research_request.v1"
EVIDENCE_BUNDLE_CONTRACT = "quantagent.evidence_bundle.v1"
THESIS_REVIEW_INPUT_CONTRACT = "quantagent.thesis_review_input.v1"
THESIS_STATE_CONTRACT = "quantagent.thesis_state.v1"
REPORT_CONTRACT = "quantagent.report.v1"
FIXTURE_TYPE = "quantagent.thesis_review_fixture.v1"
TRACKER_IDENTITY = "builtin.deterministic-thesis-tracker@1.0.0"

_MAX_FIXTURE_BYTES = 2 * 1024 * 1024
_SCHEMAS = {
    RESEARCH_REQUEST_CONTRACT: "quantagent.research_request.v1.schema.json",
    EVIDENCE_BUNDLE_CONTRACT: "quantagent.evidence_bundle.v1.schema.json",
    THESIS_STATE_CONTRACT: "quantagent.thesis_state.v1.schema.json",
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ContractError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ContractError(f"non-JSON number is forbidden: {value}")


def load_strict_json(path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path)
    try:
        size = fixture_path.stat().st_size
    except OSError as exc:
        raise ContractError(f"cannot inspect research fixture {fixture_path}: {exc}") from exc
    if size > _MAX_FIXTURE_BYTES:
        raise ContractError(f"research fixture exceeds {_MAX_FIXTURE_BYTES} bytes")
    try:
        raw = fixture_path.read_bytes()
        if len(raw) > _MAX_FIXTURE_BYTES:
            raise ContractError(f"research fixture exceeds {_MAX_FIXTURE_BYTES} bytes")
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot parse research fixture {fixture_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError("research fixture must be one JSON object")
    return value


@lru_cache(maxsize=None)
def _validator(contract: str) -> Draft202012Validator:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / _SCHEMAS[contract]
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        raise ContractError(f"invalid repository schema {schema_path}: {exc}") from exc
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(contract: str, value: dict[str, Any]) -> None:
    errors = sorted(
        _validator(contract).iter_errors(value),
        key=lambda item: [str(part) for part in item.absolute_path],
    )
    if errors:
        parts = []
        for error in errors[:10]:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            parts.append(f"{location}: {error.message}")
        raise ContractError(f"{contract} validation failed: {'; '.join(parts)}")


def _require_unique(rows: list[dict[str, Any]], field: str, label: str) -> None:
    values = [row[field] for row in rows]
    if len(values) != len(set(values)):
        raise ContractError(f"{label} contains duplicate {field}")


def _subject_key(subject: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        subject[field]
        for field in ("asset_type", "symbol", "venue", "base_asset", "quote_asset")
    )


def validate_research_request(value: dict[str, Any]) -> None:
    _validate_schema(RESEARCH_REQUEST_CONTRACT, value)
    requested_at = parse_aware_timestamp(value["requested_at"], "requested_at")
    as_of = parse_aware_timestamp(value["as_of"], "as_of")
    if requested_at < as_of:
        raise ContractError("requested_at cannot precede the research as_of cutoff")
    refs = {row["purpose"]: row for row in value["input_refs"]}
    if len(value["input_refs"]) != 2 or set(refs) != {
        "previous_thesis_state",
        "evidence_bundle",
    }:
        raise ContractError("input_refs must contain exactly one previous thesis and evidence bundle")
    expected_contracts = {
        "previous_thesis_state": THESIS_STATE_CONTRACT,
        "evidence_bundle": EVIDENCE_BUNDLE_CONTRACT,
    }
    for purpose, contract in expected_contracts.items():
        if refs[purpose]["contract_version"] != contract:
            raise ContractError(f"{purpose} must reference {contract}")


def _validate_timestamp_order(evidence: dict[str, Any], as_of: Any) -> None:
    published = parse_aware_timestamp(evidence["published_at"], "published_at")
    available = parse_aware_timestamp(evidence["available_at"], "available_at")
    collected = parse_aware_timestamp(evidence["collected_at"], "collected_at")
    if evidence["event_at"] is not None:
        parse_aware_timestamp(evidence["event_at"], "event_at")
    for fact in evidence["structured_facts"]:
        if fact["observed_at"] is not None:
            observed = parse_aware_timestamp(
                fact["observed_at"],
                "structured_facts.observed_at",
            )
            if observed > as_of:
                raise ContractError(
                    f"evidence {evidence['evidence_id']} contains a fact after the research "
                    "as_of cutoff"
                )
    if published > available:
        raise ContractError(f"evidence {evidence['evidence_id']} is available before publication")
    if available > collected:
        raise ContractError(f"evidence {evidence['evidence_id']} is collected before availability")
    if available > as_of:
        raise ContractError(f"evidence {evidence['evidence_id']} is after the research as_of cutoff")
    if collected > as_of:
        raise ContractError(
            f"evidence {evidence['evidence_id']} is collected after the research as_of cutoff"
        )


def validate_evidence_bundle(
    value: dict[str, Any],
    *,
    request: dict[str, Any],
    previous_thesis: dict[str, Any],
) -> None:
    _validate_schema(EVIDENCE_BUNDLE_CONTRACT, value)
    if _subject_key(value["subject"]) != _subject_key(request["subject"]):
        raise ContractError("evidence subject does not match the research request")
    if _subject_key(value["subject"]) != _subject_key(previous_thesis["subject"]):
        raise ContractError("evidence subject does not match the previous thesis")
    if value["as_of"] != request["as_of"]:
        raise ContractError("evidence bundle as_of must equal the research request as_of")
    cutoff = parse_aware_timestamp(request["as_of"], "as_of")
    _require_unique(value["evidence"], "evidence_id", "evidence bundle")
    allowed_claims = {row["claim_id"] for row in previous_thesis["claims"]}
    allowed_claims.update(
        row["condition_id"] for row in previous_thesis["invalidation_conditions"]
    )
    stance_impacts = {
        "support": {"strengthen"},
        "oppose": {"weaken", "invalidate"},
        "context": {"context"},
    }
    for evidence in value["evidence"]:
        unknown_claims = set(evidence["claim_refs"]).difference(allowed_claims)
        if unknown_claims:
            raise ContractError(
                f"evidence {evidence['evidence_id']} references unknown claims: "
                f"{sorted(unknown_claims)}"
            )
        if evidence["impact"] not in stance_impacts[evidence["stance"]]:
            raise ContractError(
                f"evidence {evidence['evidence_id']} stance and impact are inconsistent"
            )
        _validate_timestamp_order(evidence, cutoff)
        expected_hash = sha256_json(
            {
                "excerpt": evidence["excerpt"],
                "structured_facts": evidence["structured_facts"],
            }
        )
        if evidence["content_sha256"] != expected_hash:
            raise ContractError(
                f"evidence {evidence['evidence_id']} content_sha256 does not match its content"
            )


def validate_thesis_state(value: dict[str, Any]) -> None:
    _validate_schema(THESIS_STATE_CONTRACT, value)
    parse_aware_timestamp(value["as_of"], "as_of")
    _require_unique(value["claims"], "claim_id", "thesis claims")
    _require_unique(value["invalidation_conditions"], "condition_id", "invalidation conditions")
    _require_unique(value["evidence_index"], "evidence_id", "thesis evidence index")
    known_claim_refs = {row["claim_id"] for row in value["claims"]}
    known_claim_refs.update(
        row["condition_id"] for row in value["invalidation_conditions"]
    )
    stance_impacts = {
        "support": {"strengthen"},
        "oppose": {"weaken", "invalidate"},
        "context": {"context"},
    }
    for evidence in value["evidence_index"]:
        unknown_refs = set(evidence["claim_refs"]).difference(known_claim_refs)
        if unknown_refs:
            raise ContractError(
                f"thesis evidence {evidence['evidence_id']} references unknown claims: "
                f"{sorted(unknown_refs)}"
            )
        if evidence["impact"] not in stance_impacts[evidence["stance"]]:
            raise ContractError(
                f"thesis evidence {evidence['evidence_id']} stance and impact are inconsistent"
            )
    evidence_ids = {row["evidence_id"] for row in value["evidence_index"]}
    partitions = (
        set(value["supporting_evidence_refs"]),
        set(value["opposing_evidence_refs"]),
        set(value["context_evidence_refs"]),
    )
    if any(left.intersection(right) for left, right in ((partitions[0], partitions[1]), (partitions[0], partitions[2]), (partitions[1], partitions[2]))):
        raise ContractError("thesis evidence stance partitions must be disjoint")
    if set().union(*partitions) != evidence_ids:
        raise ContractError("thesis evidence stance partitions must cover the evidence index")
    expected_partitions = (
        {row["evidence_id"] for row in value["evidence_index"] if row["stance"] == "support"},
        {row["evidence_id"] for row in value["evidence_index"] if row["stance"] == "oppose"},
        {row["evidence_id"] for row in value["evidence_index"] if row["stance"] == "context"},
    )
    if partitions != expected_partitions:
        raise ContractError("thesis evidence partitions do not match evidence stance")

    for claim in value["claims"]:
        matching = [
            row for row in value["evidence_index"] if claim["claim_id"] in row["claim_refs"]
        ]
        expected_refs = {row["evidence_id"] for row in matching}
        if set(claim["evidence_refs"]) != expected_refs:
            raise ContractError(f"claim {claim['claim_id']} evidence_refs are inconsistent")
        impacts = {row["impact"] for row in matching}
        expected_status = (
            "invalidated"
            if "invalidate" in impacts
            else "challenged"
            if "weaken" in impacts
            else "supported"
            if "strengthen" in impacts
            else "untested"
        )
        if claim["status"] != expected_status:
            raise ContractError(f"claim {claim['claim_id']} status is inconsistent with evidence")

    for condition in value["invalidation_conditions"]:
        matching = [
            row
            for row in value["evidence_index"]
            if condition["condition_id"] in row["claim_refs"]
            and row["impact"] == "invalidate"
        ]
        expected_refs = {row["evidence_id"] for row in matching}
        if set(condition["evidence_refs"]) != expected_refs:
            raise ContractError(
                f"invalidation condition {condition['condition_id']} evidence_refs are inconsistent"
            )
        expected_status = "triggered" if matching else "monitoring"
        if condition["status"] != expected_status:
            raise ContractError(
                f"invalidation condition {condition['condition_id']} status is inconsistent"
            )

    if any(row["status"] == "triggered" for row in value["invalidation_conditions"]) or any(
        row["status"] == "invalidated" for row in value["claims"]
    ):
        expected_assessment = "invalidated"
    elif partitions[1] or any(row["status"] == "challenged" for row in value["claims"]):
        expected_assessment = "weakened"
    elif partitions[0]:
        expected_assessment = "intact"
    else:
        expected_assessment = "insufficient_evidence"
    if value["current_assessment"] != expected_assessment:
        raise ContractError("current_assessment is inconsistent with thesis evidence")
    expected_suggestion = {
        "intact": "research_only_maintain",
        "weakened": "research_only_reassess",
        "invalidated": "research_only_investigate",
        "insufficient_evidence": "research_only_investigate",
    }[expected_assessment]
    if value["research_suggestion"] != expected_suggestion:
        raise ContractError("research_suggestion is inconsistent with current_assessment")

    origins = {row["origin_ref"] for row in value["evidence_index"]}
    expected_sufficient = bool(partitions[0] and partitions[1] and len(origins) >= 2)
    if value["statuses"]["evidence_sufficient"] != expected_sufficient:
        raise ContractError("evidence_sufficient is inconsistent with the evidence index")
    expected_missing: set[str] = set()
    if not partitions[0]:
        expected_missing.add("supporting_evidence_missing")
    if not partitions[1]:
        expected_missing.add("opposing_evidence_missing")
    if len(origins) < 2:
        expected_missing.add("independent_source_missing")
    if set(value["missing_information"]) != expected_missing:
        raise ContractError("missing_information is inconsistent with the evidence index")
    if not set(value["revision"]["added_evidence_refs"]).issubset(evidence_ids):
        raise ContractError("revision references evidence outside the thesis state")
    previous_ref = value["previous_state_ref"]
    if value["version"] == 1 and previous_ref is not None:
        raise ContractError("version 1 thesis state cannot reference a previous version")
    if value["version"] > 1:
        if previous_ref is None:
            raise ContractError("revised thesis state must reference its previous version")
        if previous_ref["thesis_id"] != value["thesis_id"]:
            raise ContractError("previous thesis reference has a different thesis_id")
        if previous_ref["version"] != value["version"] - 1:
            raise ContractError("previous thesis reference version is not contiguous")


def validate_review_fixture(value: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "fixture_type",
        "research_request",
        "previous_thesis_state",
        "evidence_bundle",
    }
    if set(value) != expected_keys or value.get("fixture_type") != FIXTURE_TYPE:
        raise ContractError(
            "thesis review fixture must contain only fixture_type, research_request, "
            "previous_thesis_state, and evidence_bundle"
        )
    request = value["research_request"]
    previous = value["previous_thesis_state"]
    evidence = value["evidence_bundle"]
    if not all(isinstance(item, dict) for item in (request, previous, evidence)):
        raise ContractError("research request, previous thesis, and evidence bundle must be objects")
    validate_research_request(request)
    validate_thesis_state(previous)
    if _subject_key(request["subject"]) != _subject_key(previous["subject"]):
        raise ContractError("research request subject does not match the previous thesis")
    if parse_aware_timestamp(previous["as_of"], "previous thesis as_of") > parse_aware_timestamp(
        request["as_of"], "request as_of"
    ):
        raise ContractError("previous thesis cannot be newer than the research cutoff")
    expected_refs = {
        "agent_ref": ("builtin.research-agent", "1.0.0"),
        "skill_ref": ("anthropic-financial-services-adapted.thesis-tracker", "1.0.0"),
        "recipe_ref": ("thesis-tracker", "1.0.0"),
    }
    for field, expected in expected_refs.items():
        actual = request[field]
        if (actual["id"], actual["version"]) != expected:
            raise ContractError(f"research request selects an unauthorized {field}")
    expected_capabilities = {
        "source.thesis_review",
        "research.thesis_update",
        "report.thesis",
    }
    if set(request["requested_capabilities"]) != expected_capabilities:
        raise ContractError("research request capabilities do not match the thesis recipe")
    if request["budget"]["max_steps"] != 3:
        raise ContractError("research request max_steps must match the three-step thesis recipe")
    if request["budget"]["max_wall_seconds"] > 120:
        raise ContractError("research request exceeds the agent wall-clock limit")
    if request["budget"]["max_cost"] != {"amount_minor": 0, "currency": "USD"}:
        raise ContractError("the deterministic thesis recipe requires a zero model cost budget")
    if request["review_required"]:
        raise ContractError("P2 does not implement pause/resume for human review")
    validate_evidence_bundle(evidence, request=request, previous_thesis=previous)
    refs = {row["purpose"]: row for row in request["input_refs"]}
    expected_hashes = {
        "previous_thesis_state": sha256_json(previous),
        "evidence_bundle": sha256_json(evidence),
    }
    for purpose, expected_hash in expected_hashes.items():
        if refs[purpose]["content_sha256"] != expected_hash:
            raise ContractError(f"{purpose} input reference hash does not match the fixture object")
    return copy.deepcopy(value)


def _evidence_index_row(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_id": evidence["evidence_id"],
        "content_sha256": evidence["content_sha256"],
        "stance": evidence["stance"],
        "impact": evidence["impact"],
        "claim_refs": sorted(evidence["claim_refs"]),
        "source_id": evidence["source"]["source_id"],
        "origin_ref": evidence["source"]["origin_ref"],
        "source_title": evidence["source"]["title"],
        "available_at": evidence["available_at"],
    }


def update_thesis(review: dict[str, Any]) -> dict[str, Any]:
    validated = validate_review_fixture(review)
    request = validated["research_request"]
    previous = validated["previous_thesis_state"]
    bundle = validated["evidence_bundle"]
    existing = {row["evidence_id"]: row for row in previous["evidence_index"]}
    new_rows: list[dict[str, Any]] = []
    for evidence in sorted(bundle["evidence"], key=lambda row: row["evidence_id"]):
        candidate = _evidence_index_row(evidence)
        current = existing.get(evidence["evidence_id"])
        if current is not None:
            if current != candidate:
                raise ContractError(
                    "evidence id collision with different content or indexed semantics: "
                    f"{evidence['evidence_id']}"
                )
            continue
        existing[evidence["evidence_id"]] = candidate
        new_rows.append(candidate)
    if not new_rows:
        return copy.deepcopy(previous)

    evidence_index = sorted(existing.values(), key=lambda row: row["evidence_id"])
    support_refs = sorted(
        row["evidence_id"] for row in evidence_index if row["stance"] == "support"
    )
    oppose_refs = sorted(
        row["evidence_id"] for row in evidence_index if row["stance"] == "oppose"
    )
    context_refs = sorted(
        row["evidence_id"] for row in evidence_index if row["stance"] == "context"
    )

    claims = copy.deepcopy(previous["claims"])
    for claim in claims:
        matching = [row for row in evidence_index if claim["claim_id"] in row["claim_refs"]]
        impacts = {row["impact"] for row in matching}
        if "invalidate" in impacts:
            claim["status"] = "invalidated"
        elif "weaken" in impacts:
            claim["status"] = "challenged"
        elif "strengthen" in impacts:
            claim["status"] = "supported"
        else:
            claim["status"] = "untested"
        claim["evidence_refs"] = sorted(row["evidence_id"] for row in matching)

    conditions = copy.deepcopy(previous["invalidation_conditions"])
    for condition in conditions:
        matching = [
            row
            for row in evidence_index
            if condition["condition_id"] in row["claim_refs"] and row["impact"] == "invalidate"
        ]
        if matching:
            condition["status"] = "triggered"
        condition["evidence_refs"] = sorted(row["evidence_id"] for row in matching)

    if any(row["status"] == "triggered" for row in conditions) or any(
        row["status"] == "invalidated" for row in claims
    ):
        assessment = "invalidated"
    elif oppose_refs or any(row["status"] == "challenged" for row in claims):
        assessment = "weakened"
    elif support_refs:
        assessment = "intact"
    else:
        assessment = "insufficient_evidence"

    suggestion = {
        "intact": "research_only_maintain",
        "weakened": "research_only_reassess",
        "invalidated": "research_only_investigate",
        "insufficient_evidence": "research_only_investigate",
    }[assessment]
    origins = {row["origin_ref"] for row in evidence_index}
    evidence_sufficient = bool(support_refs and oppose_refs and len(origins) >= 2)
    missing_information: list[str] = []
    if not support_refs:
        missing_information.append("supporting_evidence_missing")
    if not oppose_refs:
        missing_information.append("opposing_evidence_missing")
    if len(origins) < 2:
        missing_information.append("independent_source_missing")

    added_ids = sorted(row["evidence_id"] for row in new_rows)
    reasons: list[str] = []
    if any(row["stance"] == "support" for row in new_rows):
        reasons.append("supporting_evidence_added")
    if any(row["stance"] == "oppose" for row in new_rows):
        reasons.append("opposing_evidence_added")
    if any(row["stance"] == "context" for row in new_rows):
        reasons.append("context_evidence_added")
    if any(row["status"] == "triggered" for row in conditions):
        reasons.append("invalidation_triggered")

    updated = {
        "contract_type": THESIS_STATE_CONTRACT,
        "thesis_id": previous["thesis_id"],
        "subject": copy.deepcopy(previous["subject"]),
        "version": previous["version"] + 1,
        "as_of": request["as_of"],
        "core_thesis": previous["core_thesis"],
        "claims": claims,
        "evidence_index": evidence_index,
        "supporting_evidence_refs": support_refs,
        "opposing_evidence_refs": oppose_refs,
        "context_evidence_refs": context_refs,
        "invalidation_conditions": conditions,
        "watch_items": sorted(previous["watch_items"]),
        "current_assessment": assessment,
        "research_suggestion": suggestion,
        "missing_information": sorted(missing_information),
        "previous_state_ref": {
            "thesis_id": previous["thesis_id"],
            "version": previous["version"],
            "content_sha256": sha256_json(previous),
        },
        "revision": {
            "reason_codes": sorted(reasons),
            "added_evidence_refs": added_ids,
        },
        "lineage": {
            "request_id": request["request_id"],
            "evidence_bundle_id": bundle["bundle_id"],
            "previous_thesis_sha256": sha256_json(previous),
            "evidence_bundle_sha256": sha256_json(bundle),
            "transformation": TRACKER_IDENTITY,
            "information_loss": ["evidence_excerpt_not_copied_to_thesis_state"],
        },
        "statuses": {
            "structure_valid": True,
            "evidence_sufficient": evidence_sufficient,
            "human_reviewed": False,
            "action_eligible": False,
        },
    }
    validate_thesis_state(updated)
    return updated
