from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ContractError, DataPacket, parse_aware_timestamp
from .plugins import PluginError, PluginManifest, RunContext


SIGNAL_CONTRACT = "quantagent.signal_history.v1"
QUALITY_CONTRACT = "quantagent.data_quality.v1"
REPORT_CONTRACT = "quantagent.report.v1"


def _decode_json_columns(row: dict[str, Any]) -> dict[str, Any]:
    decoded = dict(row)
    for key, value in list(decoded.items()):
        if key.endswith("_json") and isinstance(value, str):
            try:
                decoded[key[:-5]] = json.loads(value)
            except json.JSONDecodeError:
                decoded[key[:-5]] = value
    return decoded


class JsonSignalSource:
    manifest = PluginManifest(
        plugin_id="builtin.json-signal-source",
        version="1.0.0",
        capability="source.signal_history",
        input_contracts=(),
        output_contract=SIGNAL_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("JSON source does not accept an input packet")
        if not config.get("path"):
            raise PluginError("JSON source requires config.path")
        path: Path = context.assert_read_path(str(config["path"]))
        max_bytes = int(config.get("max_bytes", 50 * 1024 * 1024))
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise PluginError(f"cannot stat JSON source {path}: {exc}") from exc
        if size > max_bytes:
            raise PluginError(f"JSON source exceeds max_bytes ({size} > {max_bytes})")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginError(f"cannot read JSON source {path}: {exc}") from exc

        if isinstance(raw, list):
            records = raw
        elif isinstance(raw, dict) and isinstance(raw.get("signals"), list):
            records = raw["signals"]
        elif isinstance(raw, dict) and isinstance(raw.get("records"), list):
            records = raw["records"]
        elif isinstance(raw, dict):
            records = [raw]
        else:
            raise PluginError("JSON source must be an object or array of objects")
        if any(not isinstance(row, dict) for row in records):
            raise PluginError("JSON source records must all be objects")

        return DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source=self.manifest.plugin_id,
            records=records,
            metadata={
                "source_kind": "json",
                "source_path": str(path),
                "source_bytes": size,
                "record_count": len(records),
                "read_only": True,
            },
        )


class SqliteSignalSource:
    manifest = PluginManifest(
        plugin_id="builtin.sqlite-signal-source",
        version="1.0.0",
        capability="source.signal_history",
        input_contracts=(),
        output_contract=SIGNAL_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("SQLite source does not accept an input packet")
        if not config.get("path"):
            raise PluginError("SQLite source requires config.path")
        path: Path = context.assert_read_path(str(config["path"]))
        limit = int(config.get("limit", 10_000))
        if limit < 1 or limit > 100_000:
            raise PluginError("SQLite limit must be between 1 and 100000")
        if not path.is_file():
            raise PluginError(f"SQLite source does not exist: {path}")

        uri = path.as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "daily_signals" not in tables:
                    raise PluginError("SQLite source has no daily_signals table")
                rows = connection.execute(
                    "SELECT * FROM daily_signals ORDER BY signal_date, asset, signal_id LIMIT ?",
                    (limit,),
                ).fetchall()
                schema_version = None
                if "schema_migrations" in tables:
                    result = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
                    schema_version = result[0] if result else None
        except PluginError:
            raise
        except sqlite3.Error as exc:
            raise PluginError(f"cannot read SQLite source {path}: {exc}") from exc

        records = [_decode_json_columns(dict(row)) for row in rows]
        return DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source=self.manifest.plugin_id,
            records=records,
            metadata={
                "source_kind": "sqlite",
                "source_path": str(path),
                "table": "daily_signals",
                "schema_version": schema_version,
                "record_count": len(records),
                "row_limit": limit,
                "read_only": True,
            },
        )


class SignalDataQuality:
    manifest = PluginManifest(
        plugin_id="builtin.signal-data-quality",
        version="1.0.0",
        capability="quality.signal_history",
        input_contracts=(SIGNAL_CONTRACT,),
        output_contract=QUALITY_CONTRACT,
        permissions=frozenset(),
        retry_safe=True,
    )

    DEFAULT_REQUIRED_FIELDS = (
        "signal_id",
        "signal_date",
        "asset",
        "quote_asset",
        "bias",
        "finalized_at",
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != SIGNAL_CONTRACT:
            raise PluginError(f"data quality requires {SIGNAL_CONTRACT}")
        required = tuple(config.get("required_fields", self.DEFAULT_REQUIRED_FIELDS))
        records = list(packet.records)
        missing_counts = {
            field: sum(1 for row in records if row.get(field) in (None, ""))
            for field in required
        }
        ids = [str(row.get("signal_id")) for row in records if row.get("signal_id") not in (None, "")]
        duplicate_ids = sorted(key for key, count in Counter(ids).items() if count > 1)
        invalid_timestamps: list[dict[str, Any]] = []
        for index, row in enumerate(records):
            value = row.get("finalized_at")
            if value in (None, ""):
                continue
            try:
                parse_aware_timestamp(value, "finalized_at")
            except ContractError as exc:
                invalid_timestamps.append({"index": index, "value": value, "reason": str(exc)})

        total_cells = len(records) * len(required)
        missing_cells = sum(missing_counts.values())
        completeness = 1.0 if total_cells == 0 else round((total_cells - missing_cells) / total_cells, 6)
        score = 100
        if not records:
            score -= 50
        score -= min(40, round((1.0 - completeness) * 40))
        score -= min(20, len(duplicate_ids) * 5)
        score -= min(20, len(invalid_timestamps) * 5)
        score = max(0, score)

        flags: list[str] = []
        if not records:
            flags.append("no_records")
        flags.extend(f"missing:{field}" for field, count in missing_counts.items() if count)
        if duplicate_ids:
            flags.append("duplicate_signal_id")
        if invalid_timestamps:
            flags.append("invalid_or_naive_finalized_at")
        summary = {
            "record_count": len(records),
            "required_fields": list(required),
            "missing_counts": missing_counts,
            "completeness": completeness,
            "duplicate_signal_ids": duplicate_ids,
            "invalid_timestamps": invalid_timestamps,
            "quality_score": score,
            "quality_flags": flags,
            "source_consistency": {
                "status": "not_evaluated",
                "reason": "one source packet was provided",
            },
            "historical_calibration": {
                "status": "not_evaluated",
                "reason": "outcome evaluation is outside this recipe",
            },
        }
        return DataPacket.create(
            contract_version=QUALITY_CONTRACT,
            packet_type="data_quality_report",
            source=self.manifest.plugin_id,
            records=[summary],
            metadata={
                "input_contract": packet.contract_version,
                "input_sha256": packet.content_sha256,
                "input_source": packet.source,
                "input_metadata": packet.metadata,
                "validator": "quantagent_builtin_v1",
            },
        )


class MarkdownQualityReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-quality-report",
        version="1.0.0",
        capability="report.data_quality",
        input_contracts=(QUALITY_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != QUALITY_CONTRACT or not packet.records:
            raise PluginError(f"Markdown report requires a non-empty {QUALITY_CONTRACT} packet")
        summary = packet.records[0]
        title = str(config.get("title", "QuantAgent 历史数据体检报告"))
        report_name = str(config.get("filename", "data_quality_report.md"))
        if Path(report_name).name != report_name or not report_name.endswith(".md"):
            raise PluginError("report filename must be a plain .md filename")
        missing = summary["missing_counts"]
        lines = [
            f"# {title}",
            "",
            f"- Run ID: `{context.run_id}`",
            f"- 生成时间: `{datetime.now().astimezone().isoformat()}`",
            f"- 输入哈希: `{packet.metadata.get('input_sha256', '')}`",
            f"- 来源插件: `{packet.metadata.get('input_source', '')}`",
            f"- 记录数: **{summary['record_count']}**",
            f"- 完整度: **{summary['completeness']:.2%}**",
            f"- 质量分: **{summary['quality_score']} / 100**（仅用于数据体检，不代表数据真实概率或模型收益）",
            "",
            "## 必填字段缺失",
            "",
            "| 字段 | 缺失数 |",
            "| --- | ---: |",
        ]
        lines.extend(f"| `{field}` | {count} |" for field, count in missing.items())
        lines.extend([
            "",
            "## 其他检查",
            "",
            f"- 重复 signal_id: {len(summary['duplicate_signal_ids'])}",
            f"- 无效或无时区 finalized_at: {len(summary['invalid_timestamps'])}",
            f"- 跨来源一致性: {summary['source_consistency']['status']}（{summary['source_consistency']['reason']}）",
            f"- 历史校准: {summary['historical_calibration']['status']}（{summary['historical_calibration']['reason']}）",
            "",
            "## 标记",
            "",
        ])
        flags = summary["quality_flags"]
        lines.extend([f"- `{flag}`" for flag in flags] or ["- 无"])
        lines.extend([
            "",
            "## 范围说明",
            "",
            "本报告验证结构完整性、重复键与时间字段。它不验证预测有效性，不替代多来源对账，也不构成交易建议。",
            "",
        ])
        report_path = Path(context.run_dir) / report_name
        report_content = "\n".join(lines)
        try:
            report_path.write_text(report_content, encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot write report {report_path}: {exc}") from exc
        artifact_sha256 = hashlib.sha256(report_content.encode("utf-8")).hexdigest()

        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[{
                "path": str(report_path),
                "format": "markdown",
                "input_sha256": packet.content_sha256,
                "artifact_sha256": artifact_sha256,
            }],
            metadata={"artifact_count": 1, "title": title},
        )
