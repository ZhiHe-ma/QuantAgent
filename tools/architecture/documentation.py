"""Check document structure, links, branch identity, and affected capability notes."""
from __future__ import annotations

import json
from pathlib import Path
import re

from .graph import module_name
from .policy import registry_index

README_SECTIONS = ("职责与边界", "文件导航", "对外接口", "依赖规则", "数据与权限", "测试与验收", "已知限制")
FEATURE_SECTIONS = ("目标与非目标", "涉及模块", "接口或数据变化", "新增依赖", "测试证据", "回滚方式", "遗留问题")
PLACEHOLDER = re.compile(r"^(?:TODO|TBD|待补|待填写|占位|\.\.\.|…)[。.!！]?$", re.I)


def read_document(root: Path, relative: str, sections: tuple) -> tuple[str, list[str]]:
    errors = []
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return "", [f"missing or out-of-repository document: {relative}"]
    text = path.read_text(encoding="utf-8-sig")
    blocks = {match.group(1).strip(): match.group(2).strip() for match in
              re.finditer(r"^##\s+([^\n]+)\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)}
    for section in sections:
        body = blocks.get(section, "")
        if not body or any(PLACEHOLDER.fullmatch(line.strip()) for line in body.splitlines() if line.strip()):
            errors.append(f"{relative}: empty or placeholder section: {section}")
    for href in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        href = href.strip().strip("<>").split("#", 1)[0]
        if not href or re.match(r"^[a-zA-Z][\w+.-]*:", href):
            continue
        target = (path.parent / href).resolve()
        if not target.is_relative_to(root.resolve()) or not target.exists():
            errors.append(f"{relative}: broken local link: {href}")
    return text, errors


def check(root: Path, registry: dict, branch: str, changed: list[str], mode: str,
          previous_registry: dict | None = None) -> list[str]:
    components, ownership = registry_index(registry)
    previous, previous_ownership = registry_index(previous_registry) if previous_registry else ({}, {})
    known = previous | components
    errors = []
    for parent in registry.get("directory_roots", []):
        directory = (root / parent).resolve()
        if not directory.is_relative_to(root.resolve()) or not directory.is_dir():
            errors.append(f"missing or invalid independent directory root: {parent}")
            continue
        for child in sorted(directory.iterdir()):
            if child.is_dir() and any(p.is_file() for p in child.rglob('*')):
                relative = child.relative_to(root.resolve()).as_posix() + "/"
                if not any(relative in c['assets'] and c['readme'] == relative + 'README.md' for c in components.values()):
                    errors.append(f"independent directory requires capability and own README: {relative}")
    for readme in sorted({item["readme"] for item in components.values()} | set(registry.get("additional_readmes", []))):
        _, findings = read_document(root, readme, README_SECTIONS)
        errors.extend(findings)
    documents = []
    for path in sorted((root / "docs/features").glob("*.md")):
        if path.name == "README.md":
            continue
        relative = path.relative_to(root).as_posix()
        text, findings = read_document(root, relative, FEATURE_SECTIONS)
        errors.extend(findings)
        match = re.search(r"```json\s*\n(.*?)\n```", text, re.S)
        try:
            meta = json.loads(match.group(1)) if match else None
            if not isinstance(meta, dict) or not isinstance(meta.get("branch"), str) or not meta["branch"] or not re.fullmatch(r"[0-9a-f]{40}", meta.get("base_commit", "")):
                raise ValueError("branch and full base commit are required")
            if not isinstance(meta.get("components"), list) or any(not isinstance(x, str) or not x for x in meta["components"]) or not isinstance(meta.get("readme_unchanged"), dict):
                raise ValueError("invalid component or README declarations")
            for name, reason in meta["readme_unchanged"].items():
                if name not in meta["components"] or not isinstance(reason, str) or len(reason.strip()) < 10 or PLACEHOLDER.fullmatch(reason.strip()):
                    raise ValueError("README exemptions require a capability and substantive reason")
            documents.append((relative, meta))
        except (ValueError, TypeError) as exc:
            errors.append(f"{relative}: invalid change metadata: {exc}")
    selected = [(path, meta) for path, meta in documents if
                (meta["branch"] == branch if mode == "branch" else path in changed)]
    if mode == "branch" and len(selected) != 1:
        errors.append(f"expected exactly one change document for source branch: {branch}")
    for path, meta in selected:
        if not set(meta['components']) <= known.keys():
            errors.append(f"{path}: selected change document references unknown capability")
    affected = set()
    for path in changed:
        module = module_name(path) if path.endswith(".py") else ""
        if module in ownership:
            affected.add(ownership[module]["id"])
        if module in previous_ownership:
            affected.add(previous_ownership[module]["id"])
        for name, item in [*previous.items(), *components.items()]:
            if any(path == asset or (asset.endswith("/") and path.startswith(asset)) for asset in item["assets"]):
                affected.add(name)
    for name in sorted(affected):
        matching = [meta for _, meta in selected if name in meta["components"]]
        if not matching:
            errors.append(f"affected component missing from change document: {name}")
        elif known[name]["readme"] not in changed and not any(name in m["readme_unchanged"] for m in matching):
            errors.append(f"update README or explain unchanged README: {name}")
    return errors
