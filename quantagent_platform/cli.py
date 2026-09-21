from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runner import RecipeError, RecipeRunner, default_registry


SOURCE_BINDINGS = {
    "bt-csv": ("backtest.portfolio", "builtin.bt-portfolio-backtest"),
    "daily-json": ("source.daily_context", "builtin.json-daily-context-source"),
    "json": ("source.signal_history", "builtin.json-signal-source"),
    "qlib-csv": ("research.factor", "builtin.qlib-factor-research"),
    "replay": ("source.signal_history", "builtin.packet-replay-source"),
    "sqlite": ("source.signal_history", "builtin.sqlite-signal-source"),
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantagent-platform")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog = subparsers.add_parser("catalog", help="show installed allow-listed plugins")
    catalog.add_argument("--json", action="store_true", dest="as_json")

    validate = subparsers.add_parser("validate-recipe", help="validate recipe structure and plugin compatibility")
    validate.add_argument("recipe")
    validate.add_argument("--source", choices=sorted(SOURCE_BINDINGS), default="sqlite")

    run = subparsers.add_parser("run", help="run a verified recipe")
    run.add_argument("recipe")
    run.add_argument("--source", choices=sorted(SOURCE_BINDINGS), required=True)
    run.add_argument("--input", required=True, dest="input_path")
    run.add_argument("--output-dir", default="artifacts/runs")
    run.add_argument("--allow-read-root", action="append", default=[])
    run.add_argument("--allow-write-root", action="append", default=[])
    run.add_argument("--allow-permission", action="append", default=[])
    run.add_argument("--param", action="append", type=_key_value, default=[], metavar="KEY=VALUE")
    run.add_argument("--bind", action="append", type=_key_value, default=[], metavar="CAPABILITY=PLUGIN")
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
        source_capability, source_plugin = SOURCE_BINDINGS[args.source]
        binding = {source_capability: source_plugin}
        if args.command == "validate-recipe":
            runner._preflight(
                recipe,
                binding,
                {"filesystem:read", "filesystem:write", "process:spawn"},
                offline=True,
            )
            print("Recipe validation passed")
            return 0

        input_path = Path(args.input_path).expanduser().resolve()
        roots = [Path(value).expanduser().resolve() for value in args.allow_read_root]
        if not roots:
            roots = [input_path.parent]
        write_roots = [Path(value).expanduser().resolve() for value in args.allow_write_root]
        params = {
            "source_path": str(input_path),
            "report_title": args.title,
        }
        params.update(dict(args.param))
        binding.update({str(key): str(value) for key, value in args.bind})
        result = runner.run(
            recipe,
            params=params,
            output_dir=args.output_dir,
            allowed_read_roots=roots,
            allowed_write_roots=write_roots or None,
            allowed_permissions={"filesystem:read", "filesystem:write", *args.allow_permission},
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
