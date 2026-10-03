"""Measure active documents and explicit reading plans; never execute sources."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .policy import registry_index

POLICY = "docs/architecture/documentation-budget.json"
CORE_DOCUMENTS = ("AGENTS.md", "docs/ARCHITECTURE.md", "docs/DEVELOPMENT_TESTING.md")
MEASUREMENT = "Unicode characters after UTF-8 BOM removal and newline normalization; not model tokens"


def _validate(policy):
    if not isinstance(policy, dict) or set(policy) != {"version", "document", "context"}:
        raise ValueError("documentation budget requires version, document and context")
    if type(policy["version"]) is not int or policy["version"] != 1:
        raise ValueError("unsupported documentation budget version")
    for section in ("document", "context"):
        limits = policy[section]
        if not isinstance(limits, dict) or set(limits) != {"max_lines", "max_characters"}:
            raise ValueError(f"invalid documentation budget section: {section}")
        if any(type(value) is not int or value <= 0 for value in limits.values()):
            raise ValueError(f"documentation budget limits must be positive integers: {section}")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate documentation budget key: {key}")
        result[key] = value
    return result


def load_policy(root: Path, *, previous: dict | None = None) -> dict:
    root = root.resolve()
    path = (root / POLICY).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"out-of-repository documentation budget: {POLICY}")
    policy = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_pairs)
    _validate(policy)
    if previous is not None:
        _validate(previous)
        for section in ("document", "context"):
            for dimension in ("max_lines", "max_characters"):
                if policy[section][dimension] > previous[section][dimension]:
                    raise ValueError(f"documentation budget limit cannot increase: {section}.{dimension}")
    return policy


def _measure(root, paths):
    documents, errors, seen = [], [], set()
    root = root.resolve()
    for relative in paths:
        try:
            path = (root / relative).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f"out-of-repository document: {relative}")
            if not path.is_file():
                raise ValueError(f"missing document: {relative}")
            if path in seen:
                continue
            seen.add(path)
            text = path.read_text(encoding="utf-8-sig")
            documents.append({"path": path.relative_to(root).as_posix(), "lines": len(text.splitlines()),
                              "characters": len(text), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        except (ValueError, OSError) as exc:
            errors.append(str(exc))
    return documents, errors


def _overflow(values, limits, label):
    return [f"{label}: {dimension} {values[dimension]} exceeds {limit}"
            for dimension, limit in (("lines", limits["max_lines"]), ("characters", limits["max_characters"]))
            if values[dimension] > limit]


def reading_bundle(root: Path, registry: dict, names: list[str], policy: dict) -> dict:
    _validate(policy)
    components, _ = registry_index(registry)
    names = list(dict.fromkeys(names))
    errors = [f"unknown capability: {name}" for name in names if name not in components]
    if not names:
        errors.append("reading plan requires at least one capability")
    documents, findings = _measure(root, [*CORE_DOCUMENTS, *(components[n]["readme"] for n in names if n in components)])
    errors.extend(findings)
    for document in documents:
        errors.extend(_overflow(document, policy["document"], "document " + document["path"]))
    totals = {dimension: sum(d[dimension] for d in documents) for dimension in ("lines", "characters")}
    errors.extend(_overflow(totals, policy["context"], "context [" + ", ".join(names) + "]"))
    return {"status": "FAIL" if errors else "PASS", "measurement": MEASUREMENT, "components": names,
            "documents": documents, "totals": totals, "limits": policy, "errors": errors}


def check(root: Path, registry: dict, policy: dict) -> dict:
    _validate(policy)
    components, _ = registry_index(registry)
    paths = [*CORE_DOCUMENTS, "README.md", *(c["readme"] for c in components.values()),
             *registry.get("additional_readmes", [])]
    documents, errors = _measure(root, paths)
    for document in documents:
        errors.extend(_overflow(document, policy["document"], "document " + document["path"]))
    contexts = []
    for name in components:
        bundle = reading_bundle(root, registry, [name], policy)
        errors.extend(bundle["errors"])
        contexts.append({"component": name, "status": bundle["status"], "totals": bundle["totals"]})
    errors = list(dict.fromkeys(errors))
    return {"status": "FAIL" if errors else "PASS", "measurement": MEASUREMENT,
            "documents": documents, "contexts": contexts, "limits": policy, "errors": errors}
