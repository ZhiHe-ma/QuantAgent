from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .builtin_plugins import REPORT_CONTRACT
from .contracts import DataPacket
from .plugins import PluginError, PluginManifest, RunContext
from .qlib_worker import PROTOCOL_VERSION, RESULT_CONTRACT


FACTOR_RESEARCH_CONTRACT = RESULT_CONTRACT
_MAX_DATA_BYTES = 10 * 1024 * 1024
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_LOG_BYTES = 64 * 1024


def _read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    try:
        size = path.stat().st_size
        if size > max_bytes:
            raise PluginError(f"{label} exceeds {max_bytes} bytes")
        return path.read_bytes()
    except PluginError:
        raise
    except OSError as exc:
        raise PluginError(f"cannot read {label} {path}: {exc}") from exc


def _worker_environment() -> dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
    return environment


def _validate_result(response: Any, request_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(response, dict):
        raise PluginError("Qlib worker response must be an object")
    if response.get("protocol_version") != PROTOCOL_VERSION:
        raise PluginError("Qlib worker returned an incompatible protocol version")
    if response.get("request_id") != request_id:
        raise PluginError("Qlib worker response request_id does not match")
    if response.get("status") != "ok":
        error = response.get("error")
        message = error.get("message") if isinstance(error, dict) else "unknown worker error"
        raise PluginError(f"Qlib worker failed: {str(message)[:2000]}")
    result = response.get("result")
    if not isinstance(result, dict) or result.get("contract_version") != FACTOR_RESEARCH_CONTRACT:
        raise PluginError("Qlib worker returned an incompatible result contract")
    records = result.get("records")
    metadata = result.get("metadata")
    if not isinstance(records, list) or not records or any(not isinstance(row, dict) for row in records):
        raise PluginError("Qlib worker result records must be a non-empty array of objects")
    if not isinstance(metadata, dict):
        raise PluginError("Qlib worker result metadata must be an object")
    runtime = metadata.get("runtime")
    if not isinstance(runtime, dict) or not all(isinstance(runtime.get(key), str) for key in ("python", "pyqlib", "pandas")):
        raise PluginError("Qlib worker result is missing runtime versions")
    return records, metadata


class QlibFactorResearch:
    manifest = PluginManifest(
        plugin_id="builtin.qlib-factor-research",
        version="1.0.0",
        capability="research.factor",
        input_contracts=(),
        output_contract=FACTOR_RESEARCH_CONTRACT,
        permissions=frozenset({"filesystem:read", "process:spawn"}),
        retry_safe=True,
        runtime="subprocess",
        catalog_status="experimental",
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("Qlib factor research does not accept an input packet")
        options = config.get("options", {})
        if not isinstance(options, dict):
            raise PluginError("Qlib options must be an object")
        if not config.get("data_path"):
            raise PluginError("Qlib factor research requires config.data_path")
        if not options.get("python_executable"):
            raise PluginError("Qlib factor research requires options.python_executable")

        data_path: Path = context.assert_read_path(str(config["data_path"]))
        python_executable: Path = context.assert_read_path(str(options["python_executable"]))
        default_worker = Path(__file__).with_name("qlib_worker.py")
        worker_path: Path = context.assert_read_path(str(options.get("worker_path", default_worker)))
        for path, label in (
            (data_path, "Qlib data file"),
            (python_executable, "Qlib Python executable"),
            (worker_path, "Qlib worker"),
        ):
            if not path.is_file():
                raise PluginError(f"{label} does not exist or is not a file: {path}")

        data = _read_bounded(data_path, int(options.get("max_data_bytes", _MAX_DATA_BYTES)), "Qlib data")
        timeout = float(options.get("timeout_seconds", 120))
        if not 1 <= timeout <= 600:
            raise PluginError("Qlib timeout_seconds must be between 1 and 600")
        columns = options.get("columns", {
            "datetime": "datetime",
            "instrument": "instrument",
            "factor": "factor",
            "label": "label",
        })
        if not isinstance(columns, dict) or any(not isinstance(value, str) or not value for value in columns.values()):
            raise PluginError("Qlib columns must be an object of non-empty strings")

        request_id = uuid.uuid4().hex
        request_path = Path(context.run_dir) / "qlib-worker-request.json"
        response_path = Path(context.run_dir) / "qlib-worker-response.json"
        stdout_path = Path(context.run_dir) / "qlib-worker.stdout.log"
        stderr_path = Path(context.run_dir) / "qlib-worker.stderr.log"
        request = {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": request_id,
            "operation": "factor_research",
            "data_path": str(data_path),
            "data_sha256": hashlib.sha256(data).hexdigest(),
            "columns": columns,
            "min_rows_per_date": int(options.get("min_rows_per_date", 3)),
        }
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8"
        )
        try:
            with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
                completed = subprocess.run(
                    [
                        str(python_executable),
                        str(worker_path),
                        "--request",
                        str(request_path),
                        "--response",
                        str(response_path),
                    ],
                    cwd=context.run_dir,
                    env=_worker_environment(),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout,
                    check=False,
                    shell=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise PluginError(f"Qlib worker timed out after {timeout:g} seconds") from exc
        except OSError as exc:
            raise PluginError(f"cannot start Qlib worker: {exc}") from exc
        stdout = _read_bounded(stdout_path, _MAX_LOG_BYTES, "Qlib worker stdout")
        stderr = _read_bounded(stderr_path, _MAX_LOG_BYTES, "Qlib worker stderr")
        if not response_path.is_file():
            detail = stderr.decode("utf-8", errors="replace").strip()[:1000]
            raise PluginError(f"Qlib worker produced no response (exit {completed.returncode}): {detail}")
        raw_response = _read_bounded(response_path, _MAX_RESPONSE_BYTES, "Qlib worker response")
        try:
            response = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"cannot parse Qlib worker response: {exc}") from exc
        records, metadata = _validate_result(response, request_id)
        if completed.returncode != 0:
            raise PluginError(f"Qlib worker exited with code {completed.returncode} despite an OK response")
        if metadata.get("data_sha256") != request["data_sha256"]:
            raise PluginError("Qlib worker result data SHA-256 does not match the request")
        metadata = dict(metadata)
        metadata.update({
            "worker_protocol": PROTOCOL_VERSION,
            "worker_path": str(worker_path),
            "python_executable": str(python_executable),
            "worker_stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "worker_stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "isolated_process": True,
        })
        return DataPacket.create(
            contract_version=FACTOR_RESEARCH_CONTRACT,
            packet_type="factor_research",
            source=self.manifest.plugin_id,
            records=records,
            metadata=metadata,
        )


class MarkdownFactorResearchReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-factor-research-report",
        version="1.0.0",
        capability="report.factor_research",
        input_contracts=(FACTOR_RESEARCH_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != FACTOR_RESEARCH_CONTRACT or len(packet.records) != 1:
            raise PluginError(f"factor research report requires one {FACTOR_RESEARCH_CONTRACT} record")
        filename = str(config.get("filename", "qlib_factor_research.md"))
        if Path(filename).name != filename or not filename.endswith(".md"):
            raise PluginError("factor research report filename must be a plain .md filename")
        row = packet.records[0]
        runtime = packet.metadata.get("runtime", {})
        daily = row.get("daily_metrics")
        if not isinstance(daily, list):
            raise PluginError("factor research result is missing daily_metrics")

        def metric(value: Any) -> str:
            return "不可计算" if value is None else f"{float(value):.6f}"

        lines = [
            "# Qlib 因子研究报告",
            "",
            "> 状态：实验性适配器。本报告验证固定输入上的加载与指标计算，不代表收益、可交易性或任意数据源兼容。",
            "",
            "## 环境与输入",
            "",
            f"- Python：{runtime.get('python', 'unknown')}",
            f"- pyqlib：{runtime.get('pyqlib', 'unknown')}",
            f"- pandas：{runtime.get('pandas', 'unknown')}",
            f"- 加载器：{packet.metadata.get('loader', 'unknown')}",
            f"- 输入 SHA-256：`{packet.metadata.get('data_sha256', 'unknown')}`",
            f"- 数据行数：{row.get('row_count')}",
            f"- 可用行数：{row.get('usable_row_count')}",
            f"- 标的数：{row.get('instrument_count')}",
            f"- 日期数：{row.get('date_count')}",
            "",
            "## 汇总",
            "",
            f"- 平均 IC：{metric(row.get('mean_ic'))}",
            f"- 平均 Rank IC：{metric(row.get('mean_rank_ic'))}",
            f"- 有效 IC 日期：{row.get('valid_ic_date_count')}",
            f"- 有效 Rank IC 日期：{row.get('valid_rank_ic_date_count')}",
            "",
            "## 每日指标",
            "",
            "| 日期 | 行数 | IC | Rank IC |",
            "| --- | ---: | ---: | ---: |",
        ]
        for item in daily:
            lines.append(
                f"| {item.get('date')} | {item.get('row_count')} | {metric(item.get('ic'))} | {metric(item.get('rank_ic'))} |"
            )
        lines.extend([
            "",
            "## 边界",
            "",
            "- 未下载或验证任何行情供应商数据集。",
            "- 未执行模型训练、组合构建、交易成本建模或回测。",
            "- 单个固定样本通过，不代表任意 Qlib 版本、数据源或插件组合通过。",
            "",
        ])
        content = "\n".join(lines)
        report_path = Path(context.run_dir) / filename
        try:
            report_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot write factor research report {report_path}: {exc}") from exc
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
            metadata={"artifact_count": 1, "research_runtime": runtime},
        )
