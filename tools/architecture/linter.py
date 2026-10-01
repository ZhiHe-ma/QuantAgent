"""Generate and run Import Linter contracts from the reviewed registry."""
from __future__ import annotations

import configparser
from itertools import combinations, product
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .policy import IO_PACKAGES, allowed, registry_index


def configuration(registry: dict, exceptions: list[dict], package_roots: list[str]) -> str:
    components, _ = registry_index(registry)
    config = configparser.ConfigParser(interpolation=None)
    config["importlinter"] = {
        "root_packages": "\n" + "\n".join(package_roots),
        "include_external_packages": "True", "exclude_type_checking_imports": "False",
    }
    def internal(name):
        return any(name == root or name.startswith(root + ".") for root in package_roots)
    ignored = sorted({f"{x['source']} -> {x['target']}" for x in exceptions
                      if x["rule"] in {"dependency", "cycle"} and internal(x["source"]) and internal(x["target"])})
    def add(name, kind, fields):
        config["importlinter:contract:" + name] = {
            "name": name, "type": kind,
            "ignore_imports": "\n" + "\n".join(ignored),
            "unmatched_ignore_imports_alerting": "error", **fields,
        }
    add("all-packages-acyclic", "acyclic_siblings", {"ancestors": "\n" + "\n".join(package_roots)})
    for name, source in components.items():
        modules = [m for m in source["modules"] if internal(m)]
        forbidden = sorted(m for target in components.values() if not allowed(source, target)
                           for m in target["modules"] if internal(m))
        if source["kind"] in {"module", "contract"}:
            forbidden += sorted(IO_PACKAGES)
        if modules and forbidden:
            add("boundary-" + name, "forbidden", {
                "source_modules": "\n" + "\n".join(modules),
                "forbidden_modules": "\n" + "\n".join(forbidden), "as_packages": "False",
                "allow_indirect_imports": "True",
            })
    layers = []
    for kind in ("entry", "workflow", "adapter", "module", "contract"):
        modules = sorted(m for c in components.values() if c["kind"] == kind
                         for m in c["modules"] if internal(m))
        if modules:
            layers.append(" : ".join(modules))
    if len(layers) > 1:
        add("directional-layers", "layers", {"layers": "\n" + "\n".join(layers)})
    business = [(c["id"], sorted(m for m in c["modules"] if internal(m)))
                for c in components.values() if c["kind"] == "module"]
    # Independence is between capabilities; files inside one capability may
    # collaborate. Flat legacy modules cannot be represented as package groups.
    for (left_id, left), (right_id, right) in combinations(business, 2):
        for index, pair in enumerate(product(left, right)):
            add(f"business-independence-{left_id}-{right_id}-{index}", "independence",
                {"modules": "\n" + "\n".join(pair)})
    from io import StringIO
    output = StringIO(); config.write(output)
    return output.getvalue()


def run(root: Path, registry: dict, exceptions: list[dict]) -> dict:
    roots = sorted({m.split(".")[0] for c in registry["components"] for m in c["modules"]
                    if (root / m.split(".")[0] / "__init__.py").is_file()})
    with tempfile.TemporaryDirectory(prefix="quantagent-imports-") as tmp:
        path = Path(tmp) / "contracts.ini"
        text = configuration(registry, exceptions, roots)
        path.write_text(text, encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONUTF8"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", "from importlinter.cli import lint_imports_command; lint_imports_command()",
             "--config", str(path), "--no-cache"],
            cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    return {"exit_code": result.returncode, "output": result.stdout + result.stderr, "configuration": text}
