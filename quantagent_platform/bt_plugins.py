from __future__ import annotations

import hashlib
import math
import uuid
from pathlib import Path
from typing import Any

from .bt_worker import PROTOCOL_VERSION, RESULT_CONTRACT
from .builtin_plugins import REPORT_CONTRACT
from .contracts import DataPacket
from .isolated_runtime import execute_json_worker, read_bounded
from .plugins import PluginError, PluginManifest, RunContext


BACKTEST_RESULT_CONTRACT = RESULT_CONTRACT
_MAX_DATA_BYTES = 20 * 1024 * 1024


def _validate_result(
    response: Any,
    request_id: str,
    expected_parameters: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(response, dict):
        raise PluginError("bt worker response must be an object")
    if response.get("protocol_version") != PROTOCOL_VERSION:
        raise PluginError("bt worker returned an incompatible protocol version")
    if response.get("request_id") != request_id:
        raise PluginError("bt worker response request_id does not match")
    if response.get("status") != "ok":
        error = response.get("error")
        message = error.get("message") if isinstance(error, dict) else "unknown worker error"
        raise PluginError(f"bt worker failed: {str(message)[:2000]}")
    result = response.get("result")
    if not isinstance(result, dict) or result.get("contract_version") != BACKTEST_RESULT_CONTRACT:
        raise PluginError("bt worker returned an incompatible result contract")
    records = result.get("records")
    metadata = result.get("metadata")
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise PluginError("bt worker result must contain exactly one record")
    record = records[0]
    for key in ("strategy_metrics", "benchmark_metrics", "parameters"):
        if not isinstance(record.get(key), dict):
            raise PluginError(f"bt worker result is missing {key}")
    parameters = record["parameters"]
    for key, expected_value in expected_parameters.items():
        if parameters.get(key) != expected_value:
            raise PluginError(
                f"bt worker result parameter {key} does not match the requested value"
            )
    if not isinstance(record.get("equity_curve"), list):
        raise PluginError("bt worker result is missing equity_curve")
    if not isinstance(metadata, dict):
        raise PluginError("bt worker result metadata must be an object")
    runtime = metadata.get("runtime")
    if not isinstance(runtime, dict) or not all(
        isinstance(runtime.get(key), str) for key in ("python", "bt", "ffn", "pandas")
    ):
        raise PluginError("bt worker result is missing runtime versions")
    return records, metadata


class BtPortfolioBacktest:
    manifest = PluginManifest(
        plugin_id="builtin.bt-portfolio-backtest",
        version="1.0.0",
        capability="backtest.portfolio",
        input_contracts=(),
        output_contract=BACKTEST_RESULT_CONTRACT,
        permissions=frozenset({"filesystem:read", "process:spawn"}),
        retry_safe=True,
        runtime="subprocess",
        catalog_status="experimental",
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("bt portfolio backtest does not accept an input packet")
        options = config.get("options", {})
        if not isinstance(options, dict):
            raise PluginError("bt options must be an object")
        if not config.get("data_path"):
            raise PluginError("bt portfolio backtest requires config.data_path")
        for required in ("python_executable", "price_semantics"):
            if not options.get(required):
                raise PluginError(f"bt portfolio backtest requires options.{required}")

        data_path: Path = context.assert_read_path(str(config["data_path"]))
        python_executable: Path = context.assert_read_path(str(options["python_executable"]))
        default_worker = Path(__file__).with_name("bt_worker.py")
        worker_path: Path = context.assert_read_path(str(options.get("worker_path", default_worker)))
        for path, label in (
            (data_path, "bt data file"),
            (python_executable, "bt Python executable"),
            (worker_path, "bt worker"),
        ):
            if not path.is_file():
                raise PluginError(f"{label} does not exist or is not a file: {path}")
        data = read_bounded(data_path, int(options.get("max_data_bytes", _MAX_DATA_BYTES)), "bt data")
        price_semantics = str(options["price_semantics"])
        if price_semantics not in {"adjusted_close", "unadjusted_close", "synthetic_close"}:
            raise PluginError("bt price_semantics must be adjusted_close, unadjusted_close, or synthetic_close")
        columns = options.get("columns", {
            "timestamp": "timestamp",
            "instrument": "instrument",
            "close": "close",
            "signal": "signal",
        })
        if not isinstance(columns, dict) or set(columns) != {"timestamp", "instrument", "close", "signal"}:
            raise PluginError("bt columns must define timestamp, instrument, close, and signal")
        if any(not isinstance(value, str) or not value for value in columns.values()):
            raise PluginError("bt column names must be non-empty strings")

        request_id = uuid.uuid4().hex
        execution_lag_bars = int(options.get("execution_lag_bars", 1))
        top_n = int(options.get("top_n", 1))
        min_signal = float(options.get("min_signal", 0.0))
        initial_capital = float(options.get("initial_capital", 100000.0))
        commission_bps = float(options.get("commission_bps", 0.0))
        slippage_bps = float(options.get("slippage_bps", 0.0))
        periods_per_year = int(options.get("periods_per_year", 365))
        if execution_lag_bars < 1:
            raise PluginError("bt execution_lag_bars must be at least 1")
        if top_n < 1:
            raise PluginError("bt top_n must be at least 1")
        if not math.isfinite(min_signal):
            raise PluginError("bt min_signal must be finite")
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise PluginError("bt initial_capital must be finite and positive")
        if any(not math.isfinite(value) or value < 0 or value > 1000 for value in (commission_bps, slippage_bps)):
            raise PluginError("bt commission_bps and slippage_bps must be between 0 and 1000")
        if periods_per_year < 1 or periods_per_year > 1000000:
            raise PluginError("bt periods_per_year must be between 1 and 1000000")
        request = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "operation": "portfolio_backtest",
            "data_path": str(data_path),
            "data_sha256": hashlib.sha256(data).hexdigest(),
            "columns": columns,
            "price_semantics": price_semantics,
            "execution_lag_bars": execution_lag_bars,
            "top_n": top_n,
            "min_signal": min_signal,
            "initial_capital": initial_capital,
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
            "periods_per_year": periods_per_year,
        }
        timeout = float(options.get("timeout_seconds", 120))
        execution = execute_json_worker(
            context,
            display_name="bt",
            file_prefix="bt-worker",
            python_executable=python_executable,
            worker_path=worker_path,
            request=request,
            timeout_seconds=timeout,
        )
        expected_parameters = {
            "execution_lag_bars": execution_lag_bars,
            "execution_price_semantics": "next_eligible_bar_close",
            "top_n": top_n,
            "min_signal": min_signal,
            "initial_capital": initial_capital,
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
            "effective_proportional_cost_bps": commission_bps + slippage_bps,
            "periods_per_year": periods_per_year,
            "price_semantics": price_semantics,
            "long_only": True,
        }
        records, metadata = _validate_result(execution.response, request_id, expected_parameters)
        if execution.returncode != 0:
            raise PluginError(f"bt worker exited with code {execution.returncode} despite an OK response")
        if metadata.get("data_sha256") != request["data_sha256"]:
            raise PluginError("bt worker result data SHA-256 does not match the request")
        metadata = dict(metadata)
        metadata.update({
            "worker_protocol": PROTOCOL_VERSION,
            "worker_path": str(worker_path),
            "python_executable": str(python_executable),
            "worker_stdout_sha256": execution.stdout_sha256,
            "worker_stderr_sha256": execution.stderr_sha256,
            "isolated_process": True,
        })
        return DataPacket.create(
            contract_version=BACKTEST_RESULT_CONTRACT,
            packet_type="portfolio_backtest",
            source=self.manifest.plugin_id,
            records=records,
            metadata=metadata,
        )


class MarkdownBacktestReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-backtest-report",
        version="1.0.0",
        capability="report.backtest",
        input_contracts=(BACKTEST_RESULT_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != BACKTEST_RESULT_CONTRACT or len(packet.records) != 1:
            raise PluginError(f"backtest report requires one {BACKTEST_RESULT_CONTRACT} record")
        filename = str(config.get("filename", "bt_portfolio_backtest.md"))
        if Path(filename).name != filename or not filename.endswith(".md"):
            raise PluginError("backtest report filename must be a plain .md filename")
        row = packet.records[0]
        strategy = row.get("strategy_metrics")
        benchmark = row.get("benchmark_metrics")
        parameters = row.get("parameters")
        runtime = packet.metadata.get("runtime")
        if not all(isinstance(value, dict) for value in (strategy, benchmark, parameters, runtime)):
            raise PluginError("backtest result is missing metrics, parameters, or runtime")

        def percent(value: Any) -> str:
            return "不可计算" if value is None else f"{float(value) * 100:.4f}%"

        def number(value: Any) -> str:
            return "不可计算" if value is None else f"{float(value):.6f}"

        lines = [
            "# bt 组合回测报告",
            "",
            "> 状态：实验性适配器。结果只说明固定样本和明确假设下的程序行为，不代表未来收益或实盘可成交性。",
            "",
            "## 环境与数据",
            "",
            f"- Python：{runtime.get('python', 'unknown')}",
            f"- bt：{runtime.get('bt', 'unknown')}",
            f"- ffn：{runtime.get('ffn', 'unknown')}",
            f"- pandas：{runtime.get('pandas', 'unknown')}",
            f"- 输入 SHA-256：`{packet.metadata.get('data_sha256', 'unknown')}`",
            f"- 样本：{row.get('input_row_count')} 行，{row.get('instrument_count')} 标的，{row.get('timestamp_count')} 个时间点",
            f"- 区间：{row.get('start_timestamp_utc')} 至 {row.get('end_timestamp_utc')}",
            f"- 价格语义：{parameters.get('price_semantics')}",
            "",
            "## 执行假设",
            "",
            f"- 信号延迟：{parameters.get('execution_lag_bars')} 根 bar",
            f"- 成交价格语义：{parameters.get('execution_price_semantics')}",
            f"- 组合：只做多，最多选择 {parameters.get('top_n')} 个信号高于 {parameters.get('min_signal')} 的标的",
            f"- 手续费：{parameters.get('commission_bps')} bps",
            f"- 滑点：{parameters.get('slippage_bps')} bps（与手续费合并为比例交易成本）",
            f"- 年化周期：{parameters.get('periods_per_year')}",
            "",
            "## 结果与基线",
            "",
            "| 指标 | 因子组合 | 等权买入持有 |",
            "| --- | ---: | ---: |",
            f"| 总收益 | {percent(strategy.get('total_return_decimal'))} | {percent(benchmark.get('total_return_decimal'))} |",
            f"| CAGR | {percent(strategy.get('cagr_decimal'))} | {percent(benchmark.get('cagr_decimal'))} |",
            f"| 年化波动 | {percent(strategy.get('annualized_volatility_decimal'))} | {percent(benchmark.get('annualized_volatility_decimal'))} |",
            f"| Sharpe（无风险利率 0） | {number(strategy.get('annualized_sharpe_zero_rf'))} | {number(benchmark.get('annualized_sharpe_zero_rf'))} |",
            f"| 最大回撤 | {percent(strategy.get('max_drawdown_decimal'))} | {percent(benchmark.get('max_drawdown_decimal'))} |",
            "",
            f"- 相对基线总收益差：{percent(row.get('total_return_delta_decimal'))}",
            f"- 目标权重调整次数：{row.get('rebalance_count')}",
            f"- 目标权重换手代理值：{number(row.get('target_weight_turnover_proxy'))}",
            "",
            "## 边界",
            "",
            "- 信号强制至少延迟一根 bar，避免使用同一根收盘后才知道的信号在同一收盘成交。",
            "- 当前成本模型把手续费与滑点合并为成交金额的固定比例，不模拟盘口、容量、冲击或部分成交。",
            "- 固定小样本的 CAGR、Sharpe 等年化指标极不稳定，只用于接口验收。",
            "- 未接入真实行情供应商、订单系统或实盘交易。",
            "",
        ]
        content = "\n".join(lines)
        report_path = Path(context.run_dir) / filename
        try:
            report_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot write backtest report {report_path}: {exc}") from exc
        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[{
                "path": str(report_path),
                "format": "markdown",
                "artifact_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "input_sha256": packet.content_sha256,
            }],
            metadata={"artifact_count": 1, "backtest_runtime": runtime},
        )
