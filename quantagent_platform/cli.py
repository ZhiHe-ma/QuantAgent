from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runner import RecipeError, RecipeRunner, default_registry


SOURCE_PLUGINS = {
    "json": "builtin.json-signal-source",
    "sqlite": "builtin.sqlite-signal-source",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantagent-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="show installed allow-listed plugins")
    catalog.add_argument("--json", action="store_true", dest="as_json")

    validate = subparsers.add_parser("validate-recipe", help="validate recipe structure and plugin compatibility")
    validate.add_argument("recipe")
    validate.add_argument("--source", choices=sorted(SOURCE_PLUGINS), default="sqlite")

    run = subparsers.add_parser("run", help="run a verified recipe")
    run.add_argument("recipe")
    run.add_argument("--source", choices=sorted(SOURCE_PLUGINS), required=True)
    run.add_argument("--input", required=True, dest="input_path")
    run.add_argument("--output-dir", default="artifacts/runs")
    run.add_argument("--allow-read-root", action="append", default=[])
    run.add_argument("--title", default="QuantAgent 历史数据体检报告")
    run.add_argument("--online", action="store_true", help="allow recipes to use network-enabled plugins")
    return parser


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
        recipe = runner.load_recipe(args.recipe)
        binding = {"source.signal_history": SOURCE_PLUGINS[args.source]}
        if args.command == "validate-recipe":
            runner._preflight(
                recipe,
                binding,
                {"filesystem:read", "filesystem:write"},
                offline=True,
            )
            print("Recipe validation passed")
            return 0

        input_path = Path(args.input_path).expanduser().resolve()
        roots = [Path(value).expanduser().resolve() for value in args.allow_read_root]
        if not roots:
            roots = [input_path.parent]
        result = runner.run(
            recipe,
            params={"source_path": str(input_path), "report_title": args.title},
            output_dir=args.output_dir,
            allowed_read_roots=roots,
            bindings=binding,
            offline=not args.online,
        )
        print(json.dumps({
            "status": result.status,
            "run_id": result.run_id,
            "run_dir": str(result.run_dir),
            "final_contract": result.final_packet.contract_version,
        }, ensure_ascii=False, indent=2))
        return 0
    except RecipeError as exc:
        print(f"Recipe failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
