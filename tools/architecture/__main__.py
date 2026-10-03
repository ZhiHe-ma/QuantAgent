"""Fail-closed local/CI entry point. Git reads and static analysis only."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .budget import CORE_DOCUMENTS, POLICY as DOCUMENT_BUDGET, check as check_budget, load_policy, parse_policy, reading_bundle
from .documentation import check as check_docs
from .graph import excluded_path
from .linter import run as run_linter
from .policy import check_baseline, check_registry_change, inspect

REGISTRY = "docs/architecture/components.json"
BASELINE = "docs/architecture/legacy-baseline.json"


def git(root: Path, *args: str, optional=False) -> str | None:
    result = subprocess.run(["git", "-c", "safe.directory=" + root.as_posix(), "-C", str(root), *args],
                            capture_output=True, encoding="utf-8")
    if result.returncode:
        if optional:
            return None
        raise ValueError(result.stderr.strip())
    return result.stdout


def base_json(root: Path, revision: str, path: str, *, decoder=json.loads) -> dict | None:
    if git(root, "cat-file", "-e", f"{revision}:{path}", optional=True) is None:
        return None
    return decoder(git(root, "show", f"{revision}:{path}"))


def write_report(root: Path, destination: Path, result: dict, registry: dict, registry_path: str) -> None:
    report = (destination if destination.is_absolute() else root / destination).resolve()
    protected = [REGISTRY, BASELINE, DOCUMENT_BUDGET, registry_path, "README.md", *CORE_DOCUMENTS,
                 *(c["readme"] for c in registry["components"]), *registry.get("additional_readmes", [])]
    if report in {(root / path).resolve() for path in protected} or (
            report.is_file() and report.suffix.lower() in {".md", ".py"}):
        raise ValueError(f"report path collides with repository input: {destination}")
    report.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".architecture-report-", dir=report.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(report)
    finally:
        temporary.unlink(missing_ok=True)


def base_sources(root: Path, revision: str) -> dict[str, str]:
    sources = {}
    for path in git(root, "ls-tree", "-r", "--name-only", "-z", revision).split("\0"):
        if path.endswith(".py") and not excluded_path(path):
            sources[path] = git(root, "show", f"{revision}:{path}")
    return sources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--registry", default=REGISTRY)
    parser.add_argument("--base-ref", default=os.environ.get("ARCHITECTURE_BASE"))
    parser.add_argument("--branch", default=os.environ.get("ARCHITECTURE_BRANCH"))
    parser.add_argument("--mode", choices=("branch", "merged"))
    parser.add_argument("--inventory", action="store_true", help="report raw violations; does not approve exceptions")
    parser.add_argument("--context-for", action="append", metavar="CAPABILITY", help="report a deduplicated document reading plan; repeat for multiple capabilities")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.inventory and args.context_for:
        parser.error("--inventory and --context-for cannot be combined")
    root = args.root.resolve()
    try:
        registry = json.loads((root / args.registry).read_text(encoding="utf-8-sig"))
        if args.context_for:
            result = reading_bundle(root, registry, args.context_for, load_policy(root))
            if args.report:
                write_report(root, args.report, result, registry, args.registry)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result["errors"] else 0
        result = inspect(root, registry)
        if args.inventory:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if not args.base_ref or set(args.base_ref) == {"0"}:
            args.base_ref = "origin/" + os.environ.get("ARCHITECTURE_DEFAULT_BRANCH", "main")
        revision = git(root, "rev-parse", "--verify", "--end-of-options", args.base_ref + "^{commit}").strip()
        branch = args.branch or git(root, "branch", "--show-current").strip()
        mode = args.mode or ("merged" if branch == os.environ.get("ARCHITECTURE_DEFAULT_BRANCH", "main") else "branch")
        baseline = json.loads((root / BASELINE).read_text(encoding="utf-8-sig"))
        if baseline.get("version") != 1 or not isinstance(baseline.get("exceptions"), list) or not isinstance(baseline.get("tasks"), dict):
            raise ValueError("invalid legacy baseline")
        prior_registry = base_json(root, revision, args.registry)
        prior_baseline = base_json(root, revision, BASELINE)
        budget = check_budget(root, registry, load_policy(
            root, previous=base_json(root, revision, DOCUMENT_BUDGET, decoder=parse_policy)))
        errors = []
        errors.extend(budget["errors"])
        if (prior_registry is None) != (prior_baseline is None):
            raise ValueError("target revision contains an incomplete governance baseline")
        approved = prior_baseline["exceptions"] if prior_baseline is not None else None
        bootstrap = None
        if prior_registry is None:
            if baseline.get("origin_commit") != revision:
                errors.append("initial baseline must name the exact target revision")
            bootstrap = inspect(root, registry, base_sources(root, revision))["violations"]
        else:
            errors.extend(check_registry_change(prior_registry, registry))
            if baseline.get("origin_commit") != prior_baseline.get("origin_commit"):
                errors.append("legacy baseline origin cannot be rewritten")
        errors.extend(check_baseline(result["violations"], baseline["exceptions"], approved, bootstrap))
        for item in baseline["exceptions"]:
            if item.get("task") not in baseline["tasks"]:
                errors.append(f"unknown remediation task: {item.get('task')}")
        changed = set(git(root, "diff", "--name-only", "-z", revision, "--").split("\0"))
        changed.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
        changed.discard("")
        errors.extend(check_docs(root, registry, branch, sorted(changed), mode, prior_registry))
        linter = run_linter(root, registry, baseline["exceptions"])
        if linter["exit_code"]:
            errors.append("Import Linter failed; see report output")
        result.update({"status": "FAIL" if errors else ("PARTIAL_COMPLIANCE" if baseline["exceptions"] else "PASS"),
                       "base_commit": revision, "branch": branch, "errors": errors,
                       "legacy_count": len(baseline["exceptions"]), "import_linter": linter,
                       "documentation_budget": budget})
        if args.report:
            write_report(root, args.report, result, registry, args.registry)
        print(f"{result['status']}: {result['module_count']} modules, {result['legacy_count']} registered legacy violations; Import Linter exit={linter['exit_code']}")
        for error in errors:
            print(error, file=sys.stderr)
        if linter["exit_code"]:
            print(linter["output"], file=sys.stderr)
        return 1 if errors else 0
    except (ValueError, OSError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"architecture gate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
