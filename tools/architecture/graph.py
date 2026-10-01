"""Collect explicit imports, including local and TYPE_CHECKING imports."""
from __future__ import annotations

import ast
import os
from pathlib import Path

EXCLUDED_DIRS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "artifacts", "tests",
    ".superpowers", "node_modules", "runtime", "server_state", "10_DailyNotes",
})
TECHNICAL_DIRS = frozenset({".git", ".venv", "venv", "__pycache__", ".superpowers", "node_modules"})


def excluded_path(path: str) -> bool:
    parts = Path(path).parts
    return bool(parts) and (parts[0] in EXCLUDED_DIRS or bool(set(parts) & TECHNICAL_DIRS))


def module_name(path: str) -> str:
    parts = list(Path(path).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def read_sources(root: Path) -> dict[str, str]:
    result = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(x for x in folders if not excluded_path(
            (Path(directory) / x).relative_to(root).as_posix()))
        for name in sorted(files):
            if name.endswith(".py"):
                path = Path(directory) / name
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f"source is outside repository: {path}")
                result[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8-sig")
    return result


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _name(node.value) + "." + node.attr
    return ""


def collect(sources: dict[str, str]) -> dict:
    names = {module_name(path) for path in sources}
    modules = {}
    for path, source in sorted(sources.items()):
        module = module_name(path)
        package = module if path.endswith("/__init__.py") else module.rpartition(".")[0]
        tree = ast.parse(source, filename=path)
        aliases = {}
        imports = []
        def add(target, member, node, dynamic=False):
            imports.append({"target": target, "member": member,
                            "line": node.lineno, "dynamic": dynamic})
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases.setdefault(alias.asname or alias.name.split(".")[0], set()).add(
                        alias.name if alias.asname else alias.name.split(".")[0])
                    add(alias.name, "", node)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = package.split(".") if package else []
                    base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
                for alias in node.names:
                    full = base + "." + alias.name
                    target, member = (full, "") if full in names else (base, alias.name)
                    aliases.setdefault(alias.asname or alias.name, set()).add(full)
                    add(target, member, node)
        for node in ast.walk(tree):
            # Conservatively retain all imported bindings: a local alias must never
            # erase a module-level one. Attribute access to submodules is allowed;
            # access to exports of the package root is a real facade dependency.
            if isinstance(node, ast.Attribute):
                prefix = _name(node.value)
                first, _, rest = prefix.partition(".")
                for binding in aliases.get(first, set()):
                    target = binding + ("." + rest if rest else "")
                    if target in names and target + "." + node.attr not in names:
                        add(target, node.attr, node)
            if isinstance(node, ast.Call):
                name = _name(node.func)
                first, _, rest = name.partition(".")
                for binding in aliases.get(first, {first}):
                    resolved = binding + ("." + rest if rest else "")
                    if resolved in {"__import__", "importlib.import_module", "importlib.util.spec_from_file_location",
                                    "importlib.util.module_from_spec", "exec", "eval"} or resolved.endswith(".exec_module"):
                        target = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else "<dynamic>"
                        add(target, "", node, dynamic=True)
        modules[module] = {"path": path, "imports": imports}
    edges = {name: set() for name in modules}
    for name, data in modules.items():
        edges[name].update(i["target"] for i in data["imports"] if i["target"] in modules)
    index, low, stack, active, cycles = {}, {}, [], set(), []
    def visit(node):
        index[node] = low[node] = len(index)
        stack.append(node); active.add(node)
        for other in sorted(edges[node]):
            if other not in index:
                visit(other); low[node] = min(low[node], low[other])
            elif other in active:
                low[node] = min(low[node], index[other])
        if low[node] == index[node]:
            group = []
            while True:
                other = stack.pop(); active.remove(other); group.append(other)
                if other == node:
                    break
            if len(group) > 1 or node in edges[node]:
                cycles.append(sorted(group))
    for node in sorted(edges):
        if node not in index:
            visit(node)
    return {"modules": modules, "cycles": sorted(cycles)}
