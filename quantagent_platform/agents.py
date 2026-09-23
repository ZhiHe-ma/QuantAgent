from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .manifests import AgentCatalog, CatalogEntry, LoadedManifest, ManifestError
from .runner import RecipeError, RecipeRunner, RunResult


class AgentError(RecipeError):
    """An Agent/Skill selection failed before recipe execution."""


@dataclass(frozen=True)
class ResolvedAgentPlan:
    catalog: AgentCatalog
    agent_entry: CatalogEntry
    skill_entry: CatalogEntry
    recipe_entry: CatalogEntry
    recipe: dict[str, Any]
    bindings: dict[str, str]
    offline: bool
    resolved_plugins: tuple[tuple[dict[str, Any], Any], ...]

    @property
    def agent(self) -> dict[str, Any]:
        artifact = self.agent_entry.artifact
        if not isinstance(artifact, LoadedManifest):
            raise AgentError("resolved Agent artifact has an invalid type")
        return artifact.data

    @property
    def skill(self) -> dict[str, Any]:
        artifact = self.skill_entry.artifact
        if not isinstance(artifact, LoadedManifest):
            raise AgentError("resolved Skill artifact has an invalid type")
        return artifact.data

    def audit_context(self) -> dict[str, Any]:
        return {
            "type": "agent",
            "catalog": {
                "version": self.catalog.version,
                "sha256": self.catalog.sha256,
                "path": str(self.catalog.path),
            },
            "agent": {
                "id": self.agent_entry.identifier,
                "version": self.agent_entry.version,
                "manifest_sha256": self.agent_entry.sha256,
                "manifest_path": str(self.agent_entry.path),
            },
            "skill": {
                "id": self.skill_entry.identifier,
                "version": self.skill_entry.version,
                "manifest_sha256": self.skill_entry.sha256,
                "manifest_path": str(self.skill_entry.path),
                "package_sha256": self.skill["content"]["package_sha256"],
            },
            "recipe": {
                "id": self.recipe_entry.identifier,
                "version": self.recipe_entry.version,
                "sha256": self.recipe_entry.sha256,
                "path": str(self.recipe_entry.path),
            },
            "required_capabilities": list(self.agent["required_capabilities"]),
            "limits": dict(self.agent["limits"]),
            "review_gates": list(self.agent["review_gates"]),
        }


def default_agent_catalog_path() -> Path:
    return Path(__file__).resolve().parents[1] / "agent_catalog" / "catalog.json"


class AgentRuntime:
    def __init__(
        self,
        catalog: AgentCatalog | None = None,
        runner: RecipeRunner | None = None,
    ) -> None:
        try:
            self.catalog = catalog or AgentCatalog.load(default_agent_catalog_path())
        except ManifestError as exc:
            raise AgentError(str(exc)) from exc
        self.runner = runner or RecipeRunner()

    @staticmethod
    def _select_reference(
        references: list[dict[str, str]],
        *,
        requested_id: str | None,
        requested_version: str | None,
        label: str,
    ) -> tuple[str, str]:
        if (requested_id is None) != (requested_version is None):
            raise AgentError(f"{label} id and version must be provided together")
        if requested_id is None:
            if len(references) != 1:
                raise AgentError(f"{label} selection is ambiguous; provide an exact id and version")
            return references[0]["id"], references[0]["version"]
        requested = (requested_id, requested_version)
        allowed = {(row["id"], row["version"]) for row in references}
        if requested not in allowed:
            raise AgentError(
                f"Agent does not allow {label}: {requested_id}@{requested_version}"
            )
        return requested_id, requested_version

    @staticmethod
    def _require_verified(entry: CatalogEntry) -> None:
        if entry.status != "verified":
            raise AgentError(
                f"Agent execution requires a verified {entry.kind}: "
                f"{entry.identifier}@{entry.version} is {entry.status}"
            )

    def resolve(
        self,
        *,
        agent_id: str,
        agent_version: str,
        skill_id: str | None = None,
        skill_version: str | None = None,
        recipe_id: str | None = None,
        recipe_version: str | None = None,
        bindings: dict[str, str] | None = None,
        allowed_permissions: set[str] | None = None,
        offline: bool = True,
    ) -> ResolvedAgentPlan:
        try:
            agent_entry = self.catalog.get("agent", agent_id, agent_version)
            self._require_verified(agent_entry)
            agent_artifact = agent_entry.artifact
            if not isinstance(agent_artifact, LoadedManifest):
                raise AgentError("catalog returned an invalid Agent artifact")
            agent = agent_artifact.data

            selected_skill = self._select_reference(
                agent["skills"],
                requested_id=skill_id,
                requested_version=skill_version,
                label="Skill",
            )
            selected_recipe = self._select_reference(
                agent["recipes"],
                requested_id=recipe_id,
                requested_version=recipe_version,
                label="Recipe",
            )
            skill_entry = self.catalog.get("skill", *selected_skill)
            recipe_entry = self.catalog.get("recipe", *selected_recipe)
            self._require_verified(skill_entry)
            self._require_verified(recipe_entry)
        except ManifestError as exc:
            raise AgentError(str(exc)) from exc

        skill_artifact = skill_entry.artifact
        if not isinstance(skill_artifact, LoadedManifest):
            raise AgentError("catalog returned an invalid Skill artifact")
        skill = skill_artifact.data
        recipe = recipe_entry.artifact
        if not isinstance(recipe, dict):
            raise AgentError("catalog returned an invalid Recipe artifact")
        if skill["test_status"]["state"] != "fixture_verified":
            raise AgentError(
                f"Agent execution requires a fixture_verified Skill: "
                f"{skill_entry.identifier}@{skill_entry.version} is "
                f"{skill['test_status']['state']}"
            )

        compatible_recipes = {
            (row["id"], row["version"]) for row in skill["compatible_recipes"]
        }
        if selected_recipe not in compatible_recipes:
            raise AgentError(
                f"Skill {skill_entry.identifier}@{skill_entry.version} is not compatible with "
                f"Recipe {recipe_entry.identifier}@{recipe_entry.version}"
            )
        if agent["input_contract"] not in skill["input_contracts"]:
            raise AgentError("Agent input contract is not accepted by the selected Skill")

        recipe_capabilities = [step["capability"] for step in recipe["steps"]]
        recipe_capability_set = set(recipe_capabilities)
        agent_capabilities = set(agent["required_capabilities"])
        skill_capabilities = set(skill["required_capabilities"])
        if recipe_capability_set != agent_capabilities:
            raise AgentError(
                "Agent required_capabilities must exactly match the selected Recipe capabilities"
            )
        if recipe_capability_set != skill_capabilities:
            raise AgentError(
                "Skill required_capabilities must exactly match the selected Recipe capabilities"
            )
        if len(recipe["steps"]) > agent["limits"]["max_steps"]:
            raise AgentError("selected Recipe exceeds the Agent max_steps limit")

        required_model = skill["model_requirements"]
        agent_model = agent["model_policy"]["required_capabilities"]
        if (
            any(
                agent_model[capability]
                for capability in (
                    "text_generation",
                    "structured_output",
                    "tool_calling",
                    "offline_replay",
                )
            )
            or any(
                required_model[capability]
                for capability in ("structured_output", "tool_calling", "offline_replay")
            )
            or agent["model_policy"]["allowed_models"]
        ):
            raise AgentError("P1 supports only deterministic Agents that do not require a model")
        for capability in ("structured_output", "tool_calling", "offline_replay"):
            if required_model[capability] and not agent_model[capability]:
                raise AgentError(f"Agent model policy does not satisfy Skill {capability}")
        if agent_model["min_context_tokens"] < required_model["min_context_tokens"]:
            raise AgentError("Agent model context is smaller than the Skill requirement")

        unsupported_gates = [
            gate
            for gate in agent["review_gates"]
            if gate["trigger"] != "before_run" or gate["action"] != "automatic_validation"
        ]
        if unsupported_gates:
            raise AgentError("P1 supports only automatic before_run review gates")

        effective_bindings = dict(bindings or {})
        unknown_bindings = set(effective_bindings).difference(recipe_capability_set)
        if unknown_bindings:
            raise AgentError(f"binding targets unknown Recipe capabilities: {sorted(unknown_bindings)}")
        effective_permissions = (
            {"filesystem:read", "filesystem:write"}
            if allowed_permissions is None
            else set(allowed_permissions)
        )
        try:
            resolved_plugins = self.runner._preflight(
                recipe,
                effective_bindings,
                effective_permissions,
                offline,
            )
        except RecipeError as exc:
            raise AgentError(str(exc)) from exc
        final_contract = resolved_plugins[-1][1].manifest.output_contract
        if final_contract != agent["output_contract"]:
            raise AgentError(
                f"Agent output contract {agent['output_contract']} does not match Recipe output "
                f"{final_contract}"
            )
        if final_contract not in skill["output_contracts"]:
            raise AgentError("selected Skill does not declare the Recipe output contract")

        return ResolvedAgentPlan(
            catalog=self.catalog,
            agent_entry=agent_entry,
            skill_entry=skill_entry,
            recipe_entry=recipe_entry,
            recipe=recipe,
            bindings=effective_bindings,
            offline=offline,
            resolved_plugins=tuple(resolved_plugins),
        )

    def run(
        self,
        *,
        agent_id: str,
        agent_version: str,
        params: dict[str, Any],
        output_dir: str | Path,
        allowed_read_roots: list[str | Path],
        allowed_write_roots: list[str | Path] | None = None,
        skill_id: str | None = None,
        skill_version: str | None = None,
        recipe_id: str | None = None,
        recipe_version: str | None = None,
        bindings: dict[str, str] | None = None,
        allowed_permissions: set[str] | None = None,
        offline: bool = True,
        run_id: str | None = None,
        submission_context: dict[str, Any] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> RunResult:
        plan = self.resolve(
            agent_id=agent_id,
            agent_version=agent_version,
            skill_id=skill_id,
            skill_version=skill_version,
            recipe_id=recipe_id,
            recipe_version=recipe_version,
            bindings=bindings,
            allowed_permissions=allowed_permissions,
            offline=offline,
        )
        invocation = plan.audit_context()
        if submission_context is not None:
            invocation["submission"] = dict(submission_context)
        return self.runner.run(
            plan.recipe,
            params=params,
            output_dir=output_dir,
            allowed_read_roots=allowed_read_roots,
            allowed_write_roots=allowed_write_roots,
            bindings=plan.bindings,
            allowed_permissions=allowed_permissions,
            offline=offline,
            run_id=run_id,
            invocation=invocation,
            cancel_check=cancel_check,
        )
