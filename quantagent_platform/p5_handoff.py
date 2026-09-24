"""Exact local route policy and canonical one-hop Agent handoff."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator, FormatChecker

from .contracts import ContractError, DataPacket, canonical_json, parse_aware_timestamp, sha256_json
from .p5_registry import (
    ApprovedRun, ApprovedSourceError, bounded_regular_file, strict_json,
)
if TYPE_CHECKING:
    from .agents import ResolvedAgentPlan
    from .runner import RunResult


HANDOFF_CONTRACT = "quantagent.agent_handoff.v1"
POLICY_VERSION = "quantagent.p5_sec_route.v1"
TASK_TYPE = "sec.review_fy2025_mara_riot.v1"
PARENT_ID = "builtin.sec-evidence-producer-agent"
CHILD_ID = "builtin.sec-evidence-review-agent"
_BUNDLE_CONTRACT = "quantagent.sec_evidence_bundle.v1"
_READ_WRITE = frozenset({"filesystem:read", "filesystem:write"})
_MAX_POLICY = 64 * 1024
_MAX_ENVELOPE = 16 * 1024
_MAX_BUNDLE = 2 * 1024 * 1024


class HandoffError(ValueError):
    """A fixed SEC route or handoff failed admission."""


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise HandoffError(f"{label} must be a lowercase SHA-256")
    return value


def _keys(value: Any, names: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != names:
        raise HandoffError(f"{label} has unknown or missing fields")
    return value


def _reference(value: Any, label: str, digest_field: str | None) -> None:
    keys = {"id", "version"} | ({digest_field} if digest_field else set())
    row = _keys(value, keys, label)
    if not isinstance(row["id"], str) or not row["id"]:
        raise HandoffError(f"{label} id is invalid")
    if row["version"] != "1.0.0":
        raise HandoffError(f"{label} version is not pinned to 1.0.0")
    if digest_field:
        _hash(row[digest_field], f"{label} {digest_field}")


def _validate_policy(value: dict[str, Any]) -> None:
    _keys(value, {
        "policy_version", "task_type", "source_contract", "catalog_sha256",
        "parent", "child", "limits",
    }, "route policy")
    if (
        value["policy_version"] != POLICY_VERSION
        or value["task_type"] != TASK_TYPE
        or value["source_contract"] != "quantagent.sec_approved_run.v1"
    ):
        raise HandoffError("route policy identity differs from fixed SEC case")
    _hash(value["catalog_sha256"], "catalog_sha256")
    limits = _keys(value["limits"], {
        "max_depth", "max_handoffs", "max_wall_seconds",
        "max_model_cost_minor", "currency",
    }, "route limits")
    if limits != {
        "max_depth": 1, "max_handoffs": 1, "max_wall_seconds": 120,
        "max_model_cost_minor": 0, "currency": "USD",
    }:
        raise HandoffError("route limits differ from fixed SEC budget")
    for role, expected_agent in (("parent", PARENT_ID), ("child", CHILD_ID)):
        entry = _keys(value[role], {
            "agent", "skill", "recipe", "plugins", "permissions",
        }, f"{role} route")
        _reference(entry["agent"], f"{role} Agent", "manifest_sha256")
        if entry["agent"]["id"] != expected_agent:
            raise HandoffError(f"{role} Agent differs from fixed route")
        if set(entry["skill"]) != {
            "id", "version", "manifest_sha256", "package_sha256",
        }:
            raise HandoffError(f"{role} Skill package pin is missing")
        _reference({key: entry["skill"][key] for key in (
            "id", "version", "manifest_sha256",
        )}, f"{role} Skill", "manifest_sha256")
        _hash(entry["skill"]["package_sha256"], f"{role} Skill package")
        _reference(entry["recipe"], f"{role} Recipe", "sha256")
        permissions = entry["permissions"]
        if not isinstance(permissions, list) or permissions != sorted(_READ_WRITE):
            raise HandoffError(f"{role} permissions differ from fixed route")
        plugins = entry["plugins"]
        if not isinstance(plugins, list) or not plugins:
            raise HandoffError(f"{role} route has no plugins")
        steps: set[str] = set()
        for plugin in plugins:
            _keys(plugin, {
                "step_id", "plugin_id", "version", "capability",
                "input_contracts", "output_contract", "permissions",
                "network_access",
            }, f"{role} plugin")
            if (
                not isinstance(plugin["step_id"], str)
                or not plugin["step_id"]
                or plugin["step_id"] in steps
                or not isinstance(plugin["plugin_id"], str)
                or not plugin["plugin_id"]
                or plugin["version"] != "1.0.0"
                or not isinstance(plugin["capability"], str)
                or not plugin["capability"]
                or not isinstance(plugin["output_contract"], str)
                or not plugin["output_contract"]
                or not isinstance(plugin["input_contracts"], list)
                or not all(isinstance(item, str) for item in plugin["input_contracts"])
                or plugin["network_access"] is not False
                or not isinstance(plugin["permissions"], list)
                or not set(plugin["permissions"]) <= _READ_WRITE
            ):
                raise HandoffError(f"{role} plugin binding is invalid")
            steps.add(plugin["step_id"])


@dataclass(frozen=True)
class RoutePolicy:
    data: dict[str, Any]
    sha256: str

    @classmethod
    def load(cls, path: Path) -> "RoutePolicy":
        try:
            raw = bounded_regular_file(Path(path), _MAX_POLICY)
            value = strict_json(raw)
            _validate_policy(value)
        except (ApprovedSourceError, OSError, TypeError, KeyError) as exc:
            raise HandoffError("fixed route policy failed validation") from exc
        return cls(value, _digest(raw))

    @property
    def parent(self) -> dict[str, Any]:
        return self.data["parent"]

    @property
    def child(self) -> dict[str, Any]:
        return self.data["child"]

    @property
    def version(self) -> str:
        return self.data["policy_version"]

    @property
    def max_handoffs(self) -> int:
        return self.data["limits"]["max_handoffs"]


def _plan_snapshot(plan: ResolvedAgentPlan) -> dict[str, Any]:
    return {
        "agent": {
            "id": plan.agent_entry.identifier,
            "version": plan.agent_entry.version,
            "manifest_sha256": plan.agent_entry.sha256,
        },
        "skill": {
            "id": plan.skill_entry.identifier,
            "version": plan.skill_entry.version,
            "manifest_sha256": plan.skill_entry.sha256,
            "package_sha256": plan.skill["content"]["package_sha256"],
        },
        "recipe": {
            "id": plan.recipe_entry.identifier,
            "version": plan.recipe_entry.version,
            "sha256": plan.recipe_entry.sha256,
        },
        "plugins": [{
            "step_id": step["id"],
            "plugin_id": plugin.manifest.plugin_id,
            "version": plugin.manifest.version,
            "capability": plugin.manifest.capability,
            "input_contracts": list(plugin.manifest.input_contracts),
            "output_contract": plugin.manifest.output_contract,
            "permissions": sorted(plugin.manifest.permissions),
            "network_access": plugin.manifest.network_access,
        } for step, plugin in plan.resolved_plugins],
    }


def _deterministic_agent(plan: ResolvedAgentPlan, *, can_call: bool) -> None:
    agent = plan.agent
    if agent.get("manifest_type") != "quantagent.agent_manifest.v2":
        raise HandoffError("SEC route requires AgentManifest v2")
    expected_children = ([{"id": CHILD_ID, "version": "1.0.0"}]
                         if can_call else [])
    if agent.get("callable_agents") != expected_children:
        raise HandoffError("SEC Agent callable target list differs")
    model = agent.get("model_policy", {})
    capabilities = model.get("required_capabilities", {})
    if (
        model.get("allowed_models") != []
        or any(capabilities.get(name) is not False for name in (
            "text_generation", "structured_output", "tool_calling",
            "offline_replay",
        ))
    ):
        raise HandoffError("SEC route cannot use a model")
    limits = agent.get("limits", {})
    if (
        limits.get("max_tool_calls") != (1 if can_call else 0)
        or limits.get("max_wall_seconds") != 120
        or limits.get("max_cost") != {"amount_minor": 0, "currency": "USD"}
    ):
        raise HandoffError("SEC Agent limits differ from fixed route")


def preflight_route(
    policy: RoutePolicy,
    parent: ResolvedAgentPlan,
    child: ResolvedAgentPlan,
    caller_permissions: frozenset[str],
) -> frozenset[str]:
    try:
        if (
            parent.catalog.sha256 != policy.data["catalog_sha256"]
            or child.catalog.sha256 != policy.data["catalog_sha256"]
        ):
            raise HandoffError("Agent catalog hash drifted")
        for plan, role in ((parent, "parent"), (child, "child")):
            expected = {key: value for key, value in policy.data[role].items()
                        if key != "permissions"}
            if _plan_snapshot(plan) != expected:
                raise HandoffError(f"{role} Agent/Skill/Recipe/plugin pin drifted")
            _deterministic_agent(plan, can_call=role == "parent")
            if any(plugin.manifest.catalog_status != "verified"
                   for _, plugin in plan.resolved_plugins):
                raise HandoffError(f"{role} plugin is not verified")
            grant = frozenset(policy.data[role]["permissions"])
            if any(not plugin.manifest.permissions <= grant
                   for _, plugin in plan.resolved_plugins):
                raise HandoffError(f"{role} plugin requires denied permissions")
        if (
            parent.agent["input_contract"] != policy.data["source_contract"]
            or parent.agent["output_contract"] != _BUNDLE_CONTRACT
            or child.agent["input_contract"] != HANDOFF_CONTRACT
            or child.agent["output_contract"] != "quantagent.report.v1"
        ):
            raise HandoffError("SEC Agent contract differs from fixed route")
        parent_grant = frozenset(policy.parent["permissions"])
        child_grant = frozenset(policy.child["permissions"])
        effective = caller_permissions & parent_grant & child_grant
        if effective != child_grant or not effective <= _READ_WRITE:
            raise HandoffError("SEC handoff would expand permissions")
        if parent.agent_entry.identifier == child.agent_entry.identifier:
            raise HandoffError("SEC handoff cycle is forbidden")
        return effective
    except HandoffError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise HandoffError("SEC route preflight failed") from exc


@dataclass(frozen=True)
class Handoff:
    envelope: dict[str, Any]
    raw: bytes
    sha256: str


def _schema_validate(envelope: dict[str, Any]) -> None:
    schema_path = (
        Path(__file__).resolve().parents[1] / "schemas"
        / "quantagent.agent_handoff.v1.schema.json"
    )
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(
            schema, format_checker=FormatChecker()).iter_errors(envelope))
    except (OSError, ValueError) as exc:
        raise HandoffError("handoff schema is unavailable") from exc
    if errors:
        raise HandoffError("handoff envelope violates its v1 contract")


def create_handoff(
    policy: RoutePolicy,
    parent: RunResult,
    bundle_path: Path,
    source: ApprovedRun,
    coordinator_id: str,
    completed_at: datetime,
    deadline_at: datetime,
) -> Handoff:
    if (
        not isinstance(coordinator_id, str)
        or not coordinator_id
        or len(coordinator_id) > 128
        or completed_at.tzinfo is None
        or deadline_at.tzinfo is None
        or deadline_at <= completed_at
    ):
        raise HandoffError("handoff coordinator or deadline is invalid")
    if (
        parent.status != "completed"
        or parent.final_packet.contract_version != _BUNDLE_CONTRACT
        or not parent.steps
        or parent.steps[-1].get("id") != "prepare-sec-evidence"
        or parent.steps[-1].get("status") != "completed"
        or parent.steps[-1].get("output_sha256") != parent.final_packet.content_sha256
    ):
        raise HandoffError("parent has no completed SEC evidence bundle")
    try:
        bundle_raw = bounded_regular_file(Path(bundle_path), _MAX_BUNDLE)
        bundle_packet = DataPacket.from_dict(strict_json(bundle_raw))
    except (ApprovedSourceError, ContractError) as exc:
        raise HandoffError("parent bundle artifact is invalid") from exc
    if (
        bundle_packet.contract_version != _BUNDLE_CONTRACT
        or bundle_packet.content_sha256 != parent.final_packet.content_sha256
        or bundle_packet.to_dict() != parent.final_packet.to_dict()
    ):
        raise HandoffError("parent bundle artifact differs from final packet")
    remaining = int((deadline_at - completed_at).total_seconds())
    if not 1 <= remaining <= 120:
        raise HandoffError("handoff wall budget is exhausted or invalid")
    expires_at = min(completed_at + timedelta(minutes=5), deadline_at)
    handoff_id = sha256_json({
        "coordinator_id": coordinator_id,
        "parent_run_id": parent.run_id,
        "bundle_file_sha256": _digest(bundle_raw),
    })
    envelope = {
        "contract_version": HANDOFF_CONTRACT,
        "handoff_id": handoff_id,
        "idempotency_key": coordinator_id,
        "coordinator_id": coordinator_id,
        "parent_run_id": parent.run_id,
        "parent": {
            "agent": policy.parent["agent"],
            "skill": policy.parent["skill"],
            "recipe": policy.parent["recipe"],
            "step_id": "prepare-sec-evidence",
        },
        "source_pins": source.to_pins(),
        "bundle": {
            "contract": _BUNDLE_CONTRACT,
            "records_sha256": bundle_packet.content_sha256,
            "file_sha256": _digest(bundle_raw),
        },
        "task_type": TASK_TYPE,
        "target": {
            "id": policy.child["agent"]["id"],
            "version": policy.child["agent"]["version"],
        },
        "created_at": completed_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "deadline_at": deadline_at.isoformat(),
        "depth": 1,
        "remaining_handoff_calls": 1,
        "remaining_wall_seconds": remaining,
        "model_cost_minor": 0,
        "model_currency": "USD",
        "effective_permissions": list(policy.child["permissions"]),
        "policy_version": policy.version,
        "policy_sha256": policy.sha256,
    }
    _schema_validate(envelope)
    raw = canonical_json(envelope).encode("utf-8")
    if len(raw) > _MAX_ENVELOPE:
        raise HandoffError("handoff envelope exceeds 16 KiB")
    return Handoff(envelope, raw, _digest(raw))


def verify_handoff(
    raw: bytes, expected_sha256: str,
    policy: RoutePolicy, now: datetime,
) -> Handoff:
    if not isinstance(raw, bytes) or len(raw) > _MAX_ENVELOPE:
        raise HandoffError("handoff envelope is too large")
    _hash(expected_sha256, "handoff hash")
    if _digest(raw) != expected_sha256:
        raise HandoffError("handoff envelope hash mismatch")
    try:
        envelope = strict_json(raw)
        canonical = canonical_json(envelope).encode("utf-8")
    except (ApprovedSourceError, ValueError, TypeError) as exc:
        raise HandoffError("handoff envelope JSON is invalid") from exc
    if canonical != raw:
        raise HandoffError("handoff envelope is not canonical JSON")
    _schema_validate(envelope)
    if (
        envelope["policy_version"] != policy.version
        or envelope["policy_sha256"] != policy.sha256
        or envelope["task_type"] != TASK_TYPE
        or envelope["target"] != {
            "id": policy.child["agent"]["id"],
            "version": policy.child["agent"]["version"],
        }
        or envelope["parent"] != {
            "agent": policy.parent["agent"],
            "skill": policy.parent["skill"],
            "recipe": policy.parent["recipe"],
            "step_id": "prepare-sec-evidence",
        }
        or envelope["effective_permissions"] != policy.child["permissions"]
        or envelope["coordinator_id"] != envelope["idempotency_key"]
        or policy.parent["agent"]["id"] == policy.child["agent"]["id"]
    ):
        raise HandoffError("handoff differs from fixed route or idempotency")
    try:
        created = parse_aware_timestamp(envelope["created_at"], "created_at")
        expires = parse_aware_timestamp(envelope["expires_at"], "expires_at")
        deadline = parse_aware_timestamp(envelope["deadline_at"], "deadline_at")
    except ContractError as exc:
        raise HandoffError("handoff has an invalid timestamp") from exc
    if (
        now.tzinfo is None
        or now < created
        or now >= expires
        or expires > deadline
        or expires > created + timedelta(minutes=5)
        or not 1 <= envelope["remaining_wall_seconds"] <= 120
        or envelope["remaining_wall_seconds"] > int((deadline - created).total_seconds())
    ):
        raise HandoffError("handoff is stale or exceeds its deadline")
    return Handoff(envelope, raw, expected_sha256)
