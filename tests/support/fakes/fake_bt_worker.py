from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


parser = argparse.ArgumentParser()
parser.add_argument("--request", required=True)
parser.add_argument("--response", required=True)
args = parser.parse_args()
if os.environ.get("QUANTAGENT_TEST_SECRET"):
    raise RuntimeError("host leaked QUANTAGENT_TEST_SECRET to worker")
request = json.loads(Path(args.request).read_text(encoding="utf-8"))
data_sha256 = hashlib.sha256(Path(request["data_path"]).read_bytes()).hexdigest()
metrics = {
    "observation_count": 10,
    "total_return_decimal": 0.05,
    "cagr_decimal": 0.1,
    "annualized_volatility_decimal": 0.2,
    "annualized_sharpe_zero_rf": 0.5,
    "max_drawdown_decimal": -0.03,
    "final_equity": 105000.0,
}
response = {
    "protocol_version": "quantagent.bt_worker.v1",
    "request_id": request["request_id"],
    "status": "ok",
    "result": {
        "contract_version": "quantagent.backtest_result.v1",
        "records": [{
            "engine": "fake protocol worker; not bt",
            "strategy": "factor_long",
            "benchmark": "equal_weight_buy_hold",
            "strategy_metrics": metrics,
            "benchmark_metrics": dict(metrics, total_return_decimal=0.04),
            "total_return_delta_decimal": 0.01,
            "rebalance_count": 4,
            "target_weight_turnover_proxy": 2.0,
            "instrument_count": 3,
            "timestamp_count": 10,
            "input_row_count": 30,
            "start_timestamp_utc": "2026-01-01T00:00:00Z",
            "end_timestamp_utc": "2026-01-10T00:00:00Z",
            "parameters": {
                "execution_lag_bars": request["execution_lag_bars"],
                "execution_price_semantics": "next_eligible_bar_close",
                "top_n": request["top_n"],
                "min_signal": request["min_signal"],
                "initial_capital": request["initial_capital"],
                "commission_bps": request["commission_bps"],
                "slippage_bps": request["slippage_bps"],
                "effective_proportional_cost_bps": request["commission_bps"] + request["slippage_bps"],
                "periods_per_year": request["periods_per_year"],
                "price_semantics": request["price_semantics"],
                "long_only": True,
            },
            "equity_curve": [],
        }],
        "metadata": {
            "data_sha256": data_sha256,
            "runtime": {"python": "test", "bt": "not-exercised", "ffn": "not-exercised", "pandas": "not-exercised"},
            "lookahead_control": "protocol fixture only",
        },
    },
}
Path(args.response).write_text(json.dumps(response), encoding="utf-8")
