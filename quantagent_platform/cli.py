from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agents import AgentError, AgentRuntime, default_agent_catalog_path
from .manifests import AgentCatalog, ManifestError
from .runner import RecipeError, RecipeRunner, default_registry


SOURCE_BINDINGS = {
    "bt-csv": ("backtest.portfolio", "builtin.bt-portfolio-backtest"),
    "daily-json": ("source.daily_context", "builtin.json-daily-context-source"),
    "json": ("source.signal_history", "builtin.json-signal-source"),
    "qlib-csv": ("research.factor", "builtin.qlib-factor-research"),
    "replay": ("source.signal_history", "builtin.packet-replay-source"),
    "sqlite": ("source.signal_history", "builtin.sqlite-signal-source"),
    "thesis-json": ("source.thesis_review", "builtin.json-thesis-review-source"),
}


def _key_value(value: str) -> tuple[str, object]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected KEY=VALUE")
    key, raw = value.split("=", 1)
    key = key.strip()
    if not key:
        raise argparse.ArgumentTypeError("parameter key cannot be empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return key, parsed


def _add_execution_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=sorted(SOURCE_BINDINGS), required=True)
    parser.add_argument("--input", required=True, dest="input_path")
    parser.add_argument("--output-dir", default="artifacts/runs")
    parser.add_argument("--allow-read-root", action="append", default=[])
    parser.add_argument("--allow-write-root", action="append", default=[])
    parser.add_argument("--allow-permission", action="append", default=[])
    parser.add_argument("--param", action="append", type=_key_value, default=[], metavar="KEY=VALUE")
    parser.add_argument("--bind", action="append", type=_key_value, default=[], metavar="CAPABILITY=PLUGIN")
    parser.add_argument("--title", default="QuantAgent 历史数据体检报告")
    parser.add_argument("--online", action="store_true", help="allow recipes to use network-enabled plugins")


def _add_agent_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("agent_id")
    parser.add_argument("--agent-version", required=True)
    parser.add_argument("--skill-id")
    parser.add_argument("--skill-version")
    parser.add_argument("--recipe-id")
    parser.add_argument("--recipe-version")
    parser.add_argument("--agent-catalog", default=str(default_agent_catalog_path()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantagent-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="show installed allow-listed plugins")
    catalog.add_argument("--json", action="store_true", dest="as_json")

    agent_catalog = subparsers.add_parser(
        "agent-catalog", help="show installed allow-listed Agents, Skills, and Recipes"
    )
    agent_catalog.add_argument("--catalog", default=str(default_agent_catalog_path()))
    agent_catalog.add_argument("--json", action="store_true", dest="as_json")

    validate = subparsers.add_parser("validate-recipe", help="validate recipe structure and plugin compatibility")
    validate.add_argument("recipe")
    validate.add_argument("--source", choices=sorted(SOURCE_BINDINGS), default="sqlite")

    validate_agent = subparsers.add_parser(
        "validate-agent", help="validate an exact Agent/Skill/Recipe selection"
    )
    _add_agent_selection_arguments(validate_agent)
    validate_agent.add_argument("--source", choices=sorted(SOURCE_BINDINGS), default="sqlite")
    validate_agent.add_argument("--allow-permission", action="append", default=[])
    validate_agent.add_argument("--bind", action="append", type=_key_value, default=[], metavar="CAPABILITY=PLUGIN")
    validate_agent.add_argument("--online", action="store_true")

    run = subparsers.add_parser("run", help="run a verified recipe")
    run.add_argument("recipe")
    _add_execution_arguments(run)

    run_agent = subparsers.add_parser("run-agent", help="run an allow-listed Agent through RecipeRunner")
    _add_agent_selection_arguments(run_agent)
    _add_execution_arguments(run_agent)
    return parser


def _selection_kwargs(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "agent_id": args.agent_id,
        "agent_version": args.agent_version,
        "skill_id": args.skill_id,
        "skill_version": args.skill_version,
        "recipe_id": args.recipe_id,
        "recipe_version": args.recipe_version,
    }


def _execution_values(
    args: argparse.Namespace,
) -> tuple[Path, list[Path], list[Path], dict[str, object], dict[str, str], set[str]]:
    input_path = Path(args.input_path).expanduser().resolve()
    roots = [Path(value).expanduser().resolve() for value in args.allow_read_root]
    if not roots:
        roots = [input_path.parent]
    write_roots = [Path(value).expanduser().resolve() for value in args.allow_write_root]
    params: dict[str, object] = {
        "source_path": str(input_path),
        "report_title": args.title,
    }
    params.update(dict(args.param))
    source_capability, source_plugin = SOURCE_BINDINGS[args.source]
    bindings = {source_capability: source_plugin}
    bindings.update({str(key): str(value) for key, value in args.bind})
    permissions = {"filesystem:read", "filesystem:write", *args.allow_permission}
    return input_path, roots, write_roots, params, bindings, permissions


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    registry = default_registry()
    runner = RecipeRunner(registry)

    if args.command == "catalog":
        rows = registry.catalog()
        if args.as_json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                print(f"{row['plugin_id']} {row['version']} [{row['status']}] -> {row['output_contract']}")
        return 0

    try:
        if args.command == "agent-catalog":
            catalog = AgentCatalog.load(args.catalog)
            rows = catalog.rows()
            if args.as_json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for row in rows:
                    print(f"{row['kind']} {row['id']} {row['version']} [{row['status']}]")
            return 0

        if args.command == "validate-agent":
            source_capability, source_plugin = SOURCE_BINDINGS[args.source]
            bindings = {source_capability: source_plugin}
            bindings.update({str(key): str(value) for key, value in args.bind})
            permissions = {"filesystem:read", "filesystem:write", *args.allow_permission}
            runtime = AgentRuntime(AgentCatalog.load(args.agent_catalog), runner)
            plan = runtime.resolve(
                **_selection_kwargs(args),
                bindings=bindings,
                allowed_permissions=permissions,
                offline=not args.online,
            )
            print(json.dumps(plan.audit_context(), ensure_ascii=False, indent=2))
            return 0

        if args.command == "validate-recipe":
            recipe = runner.load_recipe(args.recipe)
            source_capability, source_plugin = SOURCE_BINDINGS[args.source]
            runner._preflight(
                recipe,
                {source_capability: source_plugin},
                {"filesystem:read", "filesystem:write", "process:spawn"},
                offline=True,
            )
            print("Recipe validation passed")
            return 0

        _, roots, write_roots, params, bindings, permissions = _execution_values(args)
        if args.command == "run-agent":
            runtime = AgentRuntime(AgentCatalog.load(args.agent_catalog), runner)
            result = runtime.run(
                **_selection_kwargs(args),
                params=params,
                output_dir=args.output_dir,
                allowed_read_roots=roots,
                allowed_write_roots=write_roots or None,
                bindings=bindings,
                allowed_permissions=permissions,
                offline=not args.online,
            )
        else:
            recipe = runner.load_recipe(args.recipe)
            result = runner.run(
                recipe,
                params=params,
                output_dir=args.output_dir,
                allowed_read_roots=roots,
                allowed_write_roots=write_roots or None,
                allowed_permissions=permissions,
                bindings=bindings,
                offline=not args.online,
            )
        print(json.dumps({
            "status": result.status,
            "run_id": result.run_id,
            "run_dir": str(result.run_dir),
            "final_contract": result.final_packet.contract_version,
        }, ensure_ascii=False, indent=2))
        return 0
    except (AgentError, ManifestError) as exc:
        print(f"Command failed: {exc}", file=sys.stderr)
        return 2
    except RecipeError as exc:
        print(f"Recipe failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
