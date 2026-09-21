from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import sys
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "quantagent.bt_worker.v1"
RESULT_CONTRACT = "quantagent.backtest_result.v1"


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


def _require_aware_timestamp(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp values must be non-empty ISO 8601 strings")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO 8601 timestamp: {value}") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"timestamp must include a timezone offset: {value}")


def lagged_equal_weights(
    instruments: list[str],
    signals: list[list[float]],
    *,
    execution_lag_bars: int,
    top_n: int,
    min_signal: float,
) -> list[list[float]]:
    if execution_lag_bars < 1:
        raise ValueError("execution_lag_bars must be at least 1")
    if top_n < 1 or top_n > len(instruments):
        raise ValueError("top_n must be between 1 and the instrument count")
    if any(len(row) != len(instruments) for row in signals):
        raise ValueError("signal rows do not match the instrument count")
    weights: list[list[float]] = []
    for row_index in range(len(signals)):
        result = [0.0] * len(instruments)
        source_index = row_index - execution_lag_bars
        if source_index >= 0:
            ranked = [
                (float(score), instrument, column_index)
                for column_index, (instrument, score) in enumerate(zip(instruments, signals[source_index]))
                if math.isfinite(float(score)) and float(score) > min_signal
            ]
            ranked.sort(key=lambda item: (-item[0], item[1]))
            selected = ranked[:top_n]
            if selected:
                equal_weight = 1.0 / len(selected)
                for _, _, column_index in selected:
                    result[column_index] = equal_weight
        weights.append(result)
    return weights


def _performance_metrics(series: Any, periods_per_year: int) -> dict[str, float | int | None]:
    returns = series.pct_change().dropna()
    start = float(series.iloc[0])
    end = float(series.iloc[-1])
    total_return = end / start - 1.0
    drawdown = series / series.cummax() - 1.0
    volatility = None
    sharpe = None
    if len(returns) > 1:
        daily_std = _finite_float(returns.std(ddof=1))
        if daily_std is not None:
            volatility = daily_std * math.sqrt(periods_per_year)
            if daily_std > 0:
                sharpe = float(returns.mean()) / daily_std * math.sqrt(periods_per_year)
    cagr = None
    if len(series) > 1 and start > 0 and end >= 0:
        cagr = (end / start) ** (periods_per_year / (len(series) - 1)) - 1.0
    return {
        "observation_count": int(len(series)),
        "total_return_decimal": _finite_float(total_return),
        "cagr_decimal": _finite_float(cagr),
        "annualized_volatility_decimal": _finite_float(volatility),
        "annualized_sharpe_zero_rf": _finite_float(sharpe),
        "max_drawdown_decimal": _finite_float(drawdown.min()),
        "final_equity": _finite_float(end),
    }


def run_backtest(request: dict[str, Any]) -> dict[str, Any]:
    import bt
    import pandas as pd

    data_path = Path(str(request["data_path"])).resolve()
    raw = data_path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != request.get("data_sha256"):
        raise ValueError("input data SHA-256 changed after host validation")
    columns = request.get("columns")
    if not isinstance(columns, dict):
        raise ValueError("columns must be an object")
    timestamp_column = str(columns.get("timestamp", "timestamp"))
    instrument_column = str(columns.get("instrument", "instrument"))
    close_column = str(columns.get("close", "close"))
    signal_column = str(columns.get("signal", "signal"))
    required = [timestamp_column, instrument_column, close_column, signal_column]

    frame = pd.read_csv(io.BytesIO(raw))
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {missing}")
    frame = frame[required].copy()
    for value in frame[timestamp_column].tolist():
        _require_aware_timestamp(value)
    frame[timestamp_column] = pd.to_datetime(frame[timestamp_column], utc=True, errors="raise").dt.tz_localize(None)
    if frame[instrument_column].isna().any() or (frame[instrument_column].astype(str).str.strip() == "").any():
        raise ValueError("instrument values must be non-empty")
    frame[instrument_column] = frame[instrument_column].astype(str)
    frame[close_column] = pd.to_numeric(frame[close_column], errors="raise")
    frame[signal_column] = pd.to_numeric(frame[signal_column], errors="raise")
    if not frame[close_column].map(lambda value: math.isfinite(float(value)) and float(value) > 0).all():
        raise ValueError("close values must be finite and positive")
    if not frame[signal_column].map(lambda value: math.isfinite(float(value))).all():
        raise ValueError("signal values must be finite")
    if frame.duplicated([timestamp_column, instrument_column]).any():
        raise ValueError("timestamp/instrument pairs must be unique")
    frame = frame.sort_values([timestamp_column, instrument_column])
    prices = frame.pivot(index=timestamp_column, columns=instrument_column, values=close_column).sort_index()
    signals = frame.pivot(index=timestamp_column, columns=instrument_column, values=signal_column).reindex_like(prices)
    if prices.isna().any().any() or signals.isna().any().any():
        raise ValueError("the first backtest contract requires a complete price and signal panel")
    if len(prices) < 3:
        raise ValueError("backtest requires at least three timestamps")

    execution_lag_bars = int(request.get("execution_lag_bars", 1))
    top_n = int(request.get("top_n", 1))
    min_signal = float(request.get("min_signal", 0.0))
    weight_rows = lagged_equal_weights(
        [str(value) for value in prices.columns],
        [[float(value) for value in row] for row in signals.to_numpy().tolist()],
        execution_lag_bars=execution_lag_bars,
        top_n=top_n,
        min_signal=min_signal,
    )
    weights = pd.DataFrame(weight_rows, index=prices.index, columns=prices.columns)
    initial_capital = float(request.get("initial_capital", 100000.0))
    if not math.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial_capital must be finite and positive")
    commission_bps = float(request.get("commission_bps", 0.0))
    slippage_bps = float(request.get("slippage_bps", 0.0))
    if any(not math.isfinite(value) or value < 0 or value > 1000 for value in (commission_bps, slippage_bps)):
        raise ValueError("commission_bps and slippage_bps must be between 0 and 1000")
    effective_cost_rate = (commission_bps + slippage_bps) / 10000.0

    def transaction_cost(quantity: float, price: float) -> float:
        return abs(float(quantity)) * float(price) * effective_cost_rate

    strategy_name = "factor_long"
    benchmark_name = "equal_weight_buy_hold"
    strategy = bt.Strategy(strategy_name, [bt.algos.WeighTarget(weights), bt.algos.Rebalance()])
    benchmark = bt.Strategy(
        benchmark_name,
        [bt.algos.RunOnce(), bt.algos.SelectAll(), bt.algos.WeighEqually(), bt.algos.Rebalance()],
    )
    strategy_test = bt.Backtest(
        strategy,
        prices,
        initial_capital=initial_capital,
        commissions=transaction_cost,
        integer_positions=False,
        progress_bar=False,
    )
    benchmark_test = bt.Backtest(
        benchmark,
        prices,
        initial_capital=initial_capital,
        commissions=transaction_cost,
        integer_positions=False,
        progress_bar=False,
    )
    result = bt.run(strategy_test, benchmark_test, progress_bar=False)
    strategy_curve = result.prices[strategy_name].astype(float) * (initial_capital / 100.0)
    benchmark_curve = result.prices[benchmark_name].astype(float) * (initial_capital / 100.0)
    periods_per_year = int(request.get("periods_per_year", 365))
    if periods_per_year < 1 or periods_per_year > 1000000:
        raise ValueError("periods_per_year must be between 1 and 1000000")
    strategy_metrics = _performance_metrics(strategy_curve, periods_per_year)
    benchmark_metrics = _performance_metrics(benchmark_curve, periods_per_year)
    total_return_delta = None
    if strategy_metrics["total_return_decimal"] is not None and benchmark_metrics["total_return_decimal"] is not None:
        total_return_delta = float(strategy_metrics["total_return_decimal"]) - float(
            benchmark_metrics["total_return_decimal"]
        )
    weight_changes = weights.diff().abs().sum(axis=1)
    if len(weight_changes):
        weight_changes.iloc[0] = weights.iloc[0].abs().sum()
    record = {
        "engine": "bt",
        "strategy": strategy_name,
        "benchmark": benchmark_name,
        "strategy_metrics": strategy_metrics,
        "benchmark_metrics": benchmark_metrics,
        "total_return_delta_decimal": _finite_float(total_return_delta),
        "rebalance_count": int((weight_changes > 0).sum()),
        "target_weight_turnover_proxy": _finite_float(weight_changes.sum() / 2.0),
        "instrument_count": int(len(prices.columns)),
        "timestamp_count": int(len(prices.index)),
        "input_row_count": int(len(frame)),
        "start_timestamp_utc": prices.index[0].isoformat() + "Z",
        "end_timestamp_utc": prices.index[-1].isoformat() + "Z",
        "parameters": {
            "execution_lag_bars": execution_lag_bars,
            "execution_price_semantics": "next_eligible_bar_close",
            "top_n": top_n,
            "min_signal": min_signal,
            "initial_capital": initial_capital,
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
            "effective_proportional_cost_bps": commission_bps + slippage_bps,
            "periods_per_year": periods_per_year,
            "price_semantics": request["price_semantics"],
            "long_only": True,
        },
        "equity_curve": [
            {
                "timestamp_utc": timestamp.isoformat() + "Z",
                "strategy_equity": _finite_float(strategy_curve.loc[timestamp]),
                "benchmark_equity": _finite_float(benchmark_curve.loc[timestamp]),
            }
            for timestamp in strategy_curve.index
        ],
    }
    return {
        "contract_version": RESULT_CONTRACT,
        "records": [record],
        "metadata": {
            "data_sha256": actual_sha256,
            "runtime": {
                "python": platform.python_version(),
                "bt": _package_version("bt"),
                "ffn": _package_version("ffn"),
                "pandas": _package_version("pandas"),
            },
            "lookahead_control": "signals are shifted by execution_lag_bars before target weights are applied",
        },
    }


def _write_response(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quantagent-bt-worker")
    parser.add_argument("--request", required=True)
    parser.add_argument("--response", required=True)
    args = parser.parse_args(argv)
    request_id = "unknown"
    response_path = Path(args.response).resolve()
    try:
        request = json.loads(Path(args.request).resolve().read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        request_id = str(request.get("request_id", "unknown"))
        if request.get("protocol_version") != PROTOCOL_VERSION:
            raise ValueError("unsupported worker protocol version")
        if request.get("operation") != "portfolio_backtest":
            raise ValueError("unsupported worker operation")
        if request.get("price_semantics") not in {"adjusted_close", "unadjusted_close", "synthetic_close"}:
            raise ValueError("price_semantics must be adjusted_close, unadjusted_close, or synthetic_close")
        result = run_backtest(request)
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
        print(f"bt worker failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
