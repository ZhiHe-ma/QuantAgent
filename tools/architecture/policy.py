"""Exact capability boundaries and monotonically shrinking legacy debt."""
from __future__ import annotations

from pathlib import Path
import sys

from .graph import collect, read_sources

KINDS = {
    "entry": {"workflow", "contract", "bootstrap"},
    "workflow": {"workflow", "module", "contract"},
    "module": {"contract"},
    "adapter": {"module", "contract"},
    "contract": {"contract"},
    "bootstrap": {"entry", "workflow", "module", "adapter", "contract", "facade"},
    "facade": {"workflow", "module", "contract"},
    "governance": {"governance"},
}
IO_PACKAGES = frozenset({"sqlite3", "requests", "httpx", "httpx2", "urllib", "subprocess",
                         "yfinance", "fastapi", "uvicorn", "pymongo", "openai", "anthropic"})


def registry_index(registry: dict) -> tuple[dict, dict]:
    if registry.get("version") != 1 or not isinstance(registry.get("components"), list):
        raise ValueError("registry must contain version 1 and components")
    components, modules = {}, {}
    for item in registry["components"]:
        name = item.get("id")
        if not isinstance(name, str) or not name or name in components or item.get("kind") not in KINDS:
            raise ValueError(f"invalid or duplicate component: {name}")
        for field in ("modules", "public_modules", "allows", "assets"):
            if not isinstance(item.get(field), list) or any(not isinstance(x, str) or not x or any(c in x for c in "*?[") for x in item[field]):
                raise ValueError(f"{name}: {field} must contain exact names or paths")
        external = item.get("external_dependencies", [])
        if not isinstance(external, list) or any(not isinstance(x, str) or not x.isidentifier() for x in external):
            raise ValueError(f"{name}: external dependencies must be exact package roots")
        if not isinstance(item.get("readme"), str) or not item["readme"] or not isinstance(item.get("data_owner"), str) or not item["data_owner"]:
            raise ValueError(f"{name}: README and data ownership are required")
        if not set(item["public_modules"]) <= set(item["modules"]):
            raise ValueError(f"{name}: public modules must belong to the component")
        components[name] = item
        for module in item["modules"]:
            if module in modules:
                raise ValueError(f"module belongs to multiple components: {module}")
            modules[module] = item
    for item in components.values():
        if not set(item["allows"]) <= components.keys():
            raise ValueError(f"{item['id']}: unknown dependency")
    return components, modules


def allowed(source: dict, target: dict) -> bool:
    return source["id"] == target["id"] or (
        target["id"] in source["allows"] and target["kind"] in KINDS[source["kind"]]
    )


def violation_key(item: dict) -> tuple[str, str, str, str]:
    return tuple(item.get(k, "") for k in ("rule", "source", "target", "member"))


def inspect(root: Path, registry: dict, sources: dict[str, str] | None = None) -> dict:
    components, ownership = registry_index(registry)
    graph = collect(read_sources(root) if sources is None else sources)
    local_roots = {m.split('.')[0] for m in graph['modules']} | {m.split('.')[0] for m in ownership}
    found = {}
    def add(rule, source, target="", member="", line=0):
        item = {"rule": rule, "source": source, "target": target, "member": member, "line": line}
        found[violation_key(item)] = item
    for module, data in graph["modules"].items():
        owner = ownership.get(module)
        if owner is None:
            add("unregistered", module)
            continue
        for edge in data["imports"]:
            target, member = edge["target"], edge["member"]
            if edge["dynamic"]:
                add("dynamic-import", module, target, member, edge["line"])
            other = ownership.get(target)
            if other:
                if not allowed(owner, other):
                    add("dependency", module, target, line=edge["line"])
                if owner["id"] != other["id"]:
                    if other["kind"] == "facade":
                        add("facade-import", module, target, member, edge["line"])
                    if target not in other["public_modules"]:
                        add("nonpublic-import", module, target, member, edge["line"])
                    if member.startswith("_"):
                        add("private-import", module, target, member, edge["line"])
                    if member == "*":
                        add("wildcard-import", module, target, member, edge["line"])
            elif target.split(".")[0] in {"tests", "artifacts", "runtime", "server_state"}:
                add("excluded-source-import", module, target, member, edge["line"])
            elif target.split(".")[0] in local_roots and not edge["dynamic"]:
                add("unregistered-import", module, target, member, edge["line"])
            if owner["kind"] in {"module", "contract"} and target.split(".")[0] in IO_PACKAGES:
                add("external-io", module, target, line=edge["line"])
            elif owner["kind"] in {"module", "contract"} and not edge["dynamic"] and target.split('.')[0] not in local_roots | sys.stdlib_module_names | set(owner.get('external_dependencies', [])):
                add("external-dependency", module, target, line=edge["line"])
    for group in graph["cycles"]:
        for source in group:
            for edge in graph["modules"][source]["imports"]:
                if edge["target"] in group:
                    add("cycle", source, edge["target"], line=edge["line"])
    return {"module_count": len(graph["modules"]), "cycles": graph["cycles"],
            "violations": sorted(found.values(), key=violation_key), "graph": graph}


def check_baseline(current: list[dict], candidate: list[dict], approved: list[dict] | None,
                   bootstrap_violations: list[dict] | None = None) -> list[str]:
    errors = []
    keys = [violation_key(x) for x in candidate]
    if len(set(keys)) != len(keys):
        errors.append("duplicate legacy exception")
    for item in candidate:
        if any(c in str(item.get(k, "")) for k in ("source", "target", "member") for c in "*?["):
            errors.append("wildcard legacy exception is forbidden")
        if not str(item.get("reason", "")).strip() or not str(item.get("task", "")).strip():
            errors.append("legacy exception requires reason and remediation task")
    actual = {violation_key(x) for x in current}
    submitted = set(keys)
    trusted = {violation_key(x) for x in (approved if approved is not None else bootstrap_violations or [])}
    for key in sorted(submitted - trusted):
        errors.append(f"exception expansion: {key}")
    for key in sorted(actual - submitted):
        errors.append(f"new architecture violation: {key}")
    for key in sorted(submitted - actual):
        errors.append(f"remove resolved legacy exception: {key}")
    return errors


def check_registry_change(base: dict, candidate: dict) -> list[str]:
    old, old_modules = registry_index(base)
    new, new_modules = registry_index(candidate)
    errors = []
    for module in old_modules.keys() & new_modules.keys():
        before, after = old_modules[module], new_modules[module]
        if (before["id"], before["kind"], before["data_owner"]) != (after["id"], after["kind"], after["data_owner"]):
            errors.append(f"existing module ownership or layer changed: {module}")
    for name in old.keys() & new.keys():
        expanded = (set(new[name]["allows"]) - set(old[name]["allows"])) & old.keys()
        if expanded:
            errors.append(f"existing dependency policy expanded: {name}: {sorted(expanded)}")
        external = set(new[name].get('external_dependencies', [])) - set(old[name].get('external_dependencies', []))
        if external:
            errors.append(f"external dependency policy expanded; separate reviewed policy change required: {name}: {sorted(external)}")
    return errors
