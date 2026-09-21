from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "quantagent.qlib_worker.v1"
RESULT_CONTRACT = "quantagent.factor_research.v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def run_factor_research(request: dict[str, Any]) -> dict[str, Any]:
    import pandas as pd
    from qlib.data.dataset.loader import StaticDataLoader

    data_path = Path(str(request["data_path"])).resolve()
    raw = data_path.read_bytes()
    actual_sha256 = _sha256_bytes(raw)
    if actual_sha256 != request.get("data_sha256"):
        raise ValueError("input data SHA-256 changed after host validation")

    columns = request.get("columns")
    if not isinstance(columns, dict):
        raise ValueError("columns must be an object")
    datetime_column = str(columns.get("datetime", "datetime"))
    instrument_column = str(columns.get("instrument", "instrument"))
    factor_column = str(columns.get("factor", "factor"))
    label_column = str(columns.get("label", "label"))
    required = [datetime_column, instrument_column, factor_column, label_column]

    frame = pd.read_csv(io.BytesIO(raw))
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    frame = frame[required].copy()
    frame[datetime_column] = pd.to_datetime(frame[datetime_column], errors="raise")
    if frame[instrument_column].isna().any() or (frame[instrument_column].astype(str).str.strip() == "").any():
        raise ValueError("instrument values must be non-empty")
    frame[instrument_column] = frame[instrument_column].astype(str)
    frame[factor_column] = pd.to_numeric(frame[factor_column], errors="raise")
    frame[label_column] = pd.to_numeric(frame[label_column], errors="raise")
    frame = frame.set_index([datetime_column, instrument_column]).sort_index()
    frame.index = frame.index.set_names(["datetime", "instrument"])
    if frame.index.has_duplicates:
        raise ValueError("datetime/instrument pairs must be unique")

    loader = StaticDataLoader(config=frame)
    loaded = loader.load(instruments=None, start_time=None, end_time=None)
    if not isinstance(loaded, pd.DataFrame):
        raise ValueError("StaticDataLoader did not return a DataFrame")
    if not {factor_column, label_column}.issubset(loaded.columns):
        raise ValueError("StaticDataLoader output is missing factor or label columns")

    usable = loaded[[factor_column, label_column]].dropna()
    min_rows = int(request.get("min_rows_per_date", 3))
    if min_rows < 2 or min_rows > 10000:
        raise ValueError("min_rows_per_date must be between 2 and 10000")

    daily: list[dict[str, Any]] = []
    for timestamp, group in usable.groupby(level="datetime", sort=True):
        row_count = int(len(group))
        pearson_ic = None
        rank_ic = None
        if (
            row_count >= min_rows
            and int(group[factor_column].nunique()) > 1
            and int(group[label_column].nunique()) > 1
        ):
            pearson_ic = _finite_float(group[factor_column].corr(group[label_column], method="pearson"))
            rank_ic = _finite_float(group[factor_column].corr(group[label_column], method="spearman"))
        daily.append({
            "date": pd.Timestamp(timestamp).date().isoformat(),
            "row_count": row_count,
            "ic": pearson_ic,
            "rank_ic": rank_ic,
        })

    valid_ic = [row["ic"] for row in daily if row["ic"] is not None]
    valid_rank_ic = [row["rank_ic"] for row in daily if row["rank_ic"] is not None]
    record = {
        "factor_name": factor_column,
        "label_name": label_column,
        "row_count": int(len(loaded)),
        "usable_row_count": int(len(usable)),
        "instrument_count": int(loaded.index.get_level_values("instrument").nunique()),
        "date_count": int(loaded.index.get_level_values("datetime").nunique()),
        "valid_ic_date_count": len(valid_ic),
        "valid_rank_ic_date_count": len(valid_rank_ic),
        "mean_ic": _finite_float(sum(valid_ic) / len(valid_ic)) if valid_ic else None,
        "mean_rank_ic": _finite_float(sum(valid_rank_ic) / len(valid_rank_ic)) if valid_rank_ic else None,
        "daily_metrics": daily,
    }
    return {
        "contract_version": RESULT_CONTRACT,
        "records": [record],
        "metadata": {
            "data_sha256": actual_sha256,
            "loader": "qlib.data.dataset.loader.StaticDataLoader",
            "runtime": {
                "python": platform.python_version(),
                "pyqlib": _package_version("pyqlib"),
                "pandas": _package_version("pandas"),
            },
        },
    }


def _write_response(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantagent-qlib-worker")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request).resolve()
    response_path = Path(args.response).resolve()
    request_id = "unknown"
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        request_id = str(request.get("request_id", "unknown"))
        if request.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported worker protocol version")
        if request.get("operation") != "factor_research":
            raise ValueError("unsupported worker operation")
        result = run_factor_research(request)
        _write_response(response_path, {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "status": "ok",
            "result": result,
        })
        return 0
    except Exception as exc:
        try:
            _write_response(response_path, {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "status": "error",
                "error": {"type": type(exc).__name__, "message": str(exc)[:2000]},
            })
        except OSError:
            pass
        print(f"Qlib worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
