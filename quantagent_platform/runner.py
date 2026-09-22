from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bt_plugins import BtPortfolioBacktest, MarkdownBacktestReport
from .builtin_plugins import JsonSignalSource, MarkdownQualityReport, SignalDataQuality, SqliteSignalSource
from .contracts import DataPacket, utc_now
from .daily_plugins import (
    DeepSeekDailyAnalysis,
    JsonDailyContextSource,
    MarkdownDailyReport,
    ReplayDailyAnalysis,
)
from .outcome_plugins import (
    OutcomeMarkdownReport,
    PacketReplaySource,
    SignalOutcomeEvaluator,
    SqliteOutcomeWriter,
)
from .plugins import PluginError, PluginRegistry, RunContext
from .qlib_plugins import MarkdownFactorResearchReport, QlibFactorResearch


class RecipeError(RuntimeError):
    """A recipe or its selected plugin combination failed validation or execution."""


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    run_dir: Path
    final_packet: DataPacket
    steps: tuple[dict[str, Any], ...]


def default_registry() -> PluginRegistry:
    catalog_path = Path(__file__).resolve().parents[1] / "plugin_catalog" / "catalog.json"
    try:
        catalog_rows = json.loads(catalog_path.read_text(encoding="utf-8"))["plugins"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PluginError(f"cannot load curated plugin catalog {catalog_path}: {exc}") from exc
    catalog = {row["plugin_id"]: row for row in catalog_rows}
    registry = PluginRegistry()
    for plugin in (
        JsonSignalSource(),
        SqliteSignalSource(),
        PacketReplaySource(),
        SignalDataQuality(),
        SignalOutcomeEvaluator(),
        SqliteOutcomeWriter(),
        MarkdownQualityReport(),
        OutcomeMarkdownReport(),
        JsonDailyContextSource(),
        ReplayDailyAnalysis(),
        DeepSeekDailyAnalysis(),
        MarkdownDailyReport(),
        QlibFactorResearch(),
        MarkdownFactorResearchReport(),
        BtPortfolioBacktest(),
        MarkdownBacktestReport(),
    ):
        entry = catalog.get(plugin.manifest.plugin_id)
        if entry is None:
            raise PluginError(f"plugin is not present in curated catalog: {plugin.manifest.plugin_id}")
        if entry.get("version") != plugin.manifest.version:
            raise PluginError(
                f"catalog version mismatch for {plugin.manifest.plugin_id}: "
                f"{entry.get('version')} != {plugin.manifest.version}"
            )
        if entry.get("status") != plugin.manifest.catalog_status:
            raise PluginError(f"catalog status mismatch for {plugin.manifest.plugin_id}")
        registry.register(plugin)
    return registry


def _atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return cleaned or "step"


class RecipeRunner:
    def __init__(self, registry: PluginRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    @staticmethod
    def load_recipe(path: str | Path) -> dict[str, Any]:
        recipe_path = Path(path)
        try:
            recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecipeError(f"cannot load recipe {recipe_path}: {exc}") from exc
        RecipeRunner.validate_recipe(recipe)
        return recipe

    @staticmethod
    def validate_recipe(recipe: dict[str, Any]) -> None:
        if not isinstance(recipe, dict):
            raise RecipeError("recipe must be an object")
        for key in ("recipe_id", "recipe_version", "steps"):
            if key not in recipe:
                raise RecipeError(f"recipe is missing {key}")
        if not isinstance(recipe["steps"], list) or not recipe["steps"]:
            raise RecipeError("recipe.steps must be a non-empty array")
        seen: set[str] = set()
        for step in recipe["steps"]:
            if not isinstance(step, dict):
                raise RecipeError("each recipe step must be an object")
            for key in ("id", "plugin", "capability"):
                if not isinstance(step.get(key), str) or not step[key]:
                    raise RecipeError(f"recipe step is missing {key}")
            if step["id"] in seen:
                raise RecipeError(f"duplicate step id: {step['id']}")
            seen.add(step["id"])
            if not isinstance(step.get("config", {}), dict):
                raise RecipeError(f"step {step['id']} config must be an object")

    @staticmethod
    def _resolve_value(value: Any, params: dict[str, Any]) -> Any:
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            key = value[2:-1]
            if key not in params:
                raise RecipeError(f"missing recipe parameter: {key}")
            return params[key]
        if isinstance(value, dict):
            return {key: RecipeRunner._resolve_value(item, params) for key, item in value.items()}
        if isinstance(value, list):
            return [RecipeRunner._resolve_value(item, params) for item in value]
        return value

    def _preflight(
        self,
        recipe: dict[str, Any],
        bindings: dict[str, str],
        allowed_permissions: set[str],
        offline: bool,
    ) -> list[tuple[dict[str, Any], Any]]:
        resolved: list[tuple[dict[str, Any], Any]] = []
        previous_contract: str | None = None
        for step in recipe["steps"]:
            plugin_id = bindings.get(step["capability"], step["plugin"])
            try:
                plugin = self.registry.get(plugin_id)
            except PluginError as exc:
                raise RecipeError(str(exc)) from exc
            manifest = plugin.manifest
            if manifest.capability != step["capability"]:
                raise RecipeError(
                    f"step {step['id']} requires {step['capability']}, but {plugin_id} provides {manifest.capability}"
                )
            denied = manifest.permissions.difference(allowed_permissions)
            if denied:
                raise RecipeError(f"step {step['id']} requires denied permissions: {sorted(denied)}")
            if offline and manifest.network_access:
                raise RecipeError(f"step {step['id']} requests network access in offline mode")
            if previous_contract is None:
                if manifest.input_contracts:
                    raise RecipeError(f"first step {step['id']} unexpectedly requires an input packet")
            elif previous_contract not in manifest.input_contracts:
                raise RecipeError(
                    f"contract mismatch before {step['id']}: {previous_contract} not in {manifest.input_contracts}"
                )
            previous_contract = manifest.output_contract
            resolved.append((step, plugin))
        return resolved

    def run(
        self,
        recipe: dict[str, Any],
        *,
        params: dict[str, Any],
        output_dir: str | Path,
        allowed_read_roots: list[str | Path],
        allowed_write_roots: list[str | Path] | None = None,
        bindings: dict[str, str] | None = None,
        allowed_permissions: set[str] | None = None,
        offline: bool = True,
        run_id: str | None = None,
        invocation: dict[str, Any] | None = None,
    ) -> RunResult:
        self.validate_recipe(recipe)
        if invocation is not None:
            if not isinstance(invocation, dict):
                raise RecipeError("invocation audit context must be an object")
            try:
                invocation = json.loads(
                    json.dumps(invocation, ensure_ascii=False, allow_nan=False, sort_keys=True)
                )
            except (TypeError, ValueError) as exc:
                raise RecipeError(f"invocation audit context must be JSON-safe: {exc}") from exc
        bindings = dict(bindings or {})
        if allowed_permissions is None:
            allowed_permissions = {"filesystem:read", "filesystem:write"}
        else:
            allowed_permissions = set(allowed_permissions)
        resolved = self._preflight(recipe, bindings, allowed_permissions, offline)
        run_id = run_id or f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
        output_root = Path(output_dir).expanduser().resolve()
        run_dir = output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        if allowed_write_roots is None:
            allowed_write_roots = []
        context = RunContext(
            run_id=run_id,
            run_dir=run_dir,
            allowed_read_roots=tuple(Path(root).expanduser().resolve() for root in allowed_read_roots),
            allowed_write_roots=tuple(Path(root).expanduser().resolve() for root in allowed_write_roots),
            offline=offline,
        )
        state: dict[str, Any] = {
            "run_id": run_id,
            "recipe_id": recipe["recipe_id"],
            "recipe_version": recipe["recipe_version"],
            "status": "running",
            "started_at": utc_now(),
            "offline": offline,
            "allowed_permissions": sorted(allowed_permissions),
            "allowed_read_roots": [str(path) for path in context.allowed_read_roots],
            "allowed_write_roots": [str(path) for path in context.allowed_write_roots],
            "bindings": bindings,
            "steps": [],
        }
        if invocation is not None:
            state["invocation"] = invocation
        state_path = run_dir / "run.json"
        _atomic_json_write(state_path, state)
        packet: DataPacket | None = None
        try:
            for index, (step, plugin) in enumerate(resolved, start=1):
                manifest = plugin.manifest
                config = self._resolve_value(step.get("config", {}), params)
                started_at = utc_now()
                packet = plugin.run(context, packet, config)
                packet.validate()
                if packet.contract_version != manifest.output_contract:
                    raise RecipeError(
                        f"plugin {manifest.plugin_id} returned {packet.contract_version}; expected {manifest.output_contract}"
                    )
                packet_path = run_dir / f"{index:02d}-{_slug(step['id'])}.json"
                _atomic_json_write(packet_path, packet.to_dict())
                step_result = {
                    "id": step["id"],
                    "plugin_id": manifest.plugin_id,
                    "plugin_version": manifest.version,
                    "capability": manifest.capability,
                    "input_contracts": list(manifest.input_contracts),
                    "output_contract": manifest.output_contract,
                    "output_sha256": packet.content_sha256,
                    "packet_path": str(packet_path),
                    "started_at": started_at,
                    "completed_at": utc_now(),
                    "status": "completed",
                }
                state["steps"].append(step_result)
                _atomic_json_write(state_path, state)
        except Exception as exc:
            state["status"] = "failed"
            state["completed_at"] = utc_now()
            state["error"] = {"type": type(exc).__name__, "message": str(exc)}
            _atomic_json_write(state_path, state)
            if isinstance(exc, RecipeError):
                raise
            if isinstance(exc, PluginError):
                raise RecipeError(str(exc)) from exc
            raise RecipeError(f"recipe execution failed: {exc}") from exc

        if packet is None:
            raise RecipeError("recipe produced no packet")
        state["status"] = "completed"
        state["completed_at"] = utc_now()
        state["final_contract"] = packet.contract_version
        state["final_sha256"] = packet.content_sha256
        _atomic_json_write(state_path, state)
        return RunResult(
            run_id=run_id,
            status="completed",
            run_dir=run_dir,
            final_packet=packet,
            steps=tuple(state["steps"]),
        )
