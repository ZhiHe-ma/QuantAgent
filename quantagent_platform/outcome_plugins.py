from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .builtin_plugins import REPORT_CONTRACT, SIGNAL_CONTRACT
from .contracts import ContractError, DataPacket, canonical_json, parse_aware_timestamp
from .plugins import PluginError, PluginManifest, RunContext


OUTCOME_CONTRACT = "quantagent.signal_outcomes.v1"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"cannot read JSON file {path}: {exc}") from exc


class PacketReplaySource:
    """Rehydrate and verify a previously persisted signal-history packet."""

    manifest = PluginManifest(
        plugin_id="builtin.packet-replay-source",
        version="1.0.0",
        capability="source.signal_history",
        input_contracts=(),
        output_contract=SIGNAL_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is not None:
            raise PluginError("packet replay source does not accept an input packet")
        if not config.get("path"):
            raise PluginError("packet replay source requires config.path")
        path: Path = context.assert_read_path(str(config["path"]))
        try:
            original = DataPacket.from_dict(_read_json(path))
        except ContractError as exc:
            raise PluginError(f"replay packet failed integrity validation: {exc}") from exc
        if original.contract_version != SIGNAL_CONTRACT:
            raise PluginError(
                f"replay packet uses {original.contract_version}; expected {SIGNAL_CONTRACT}"
            )
        return DataPacket.create(
            contract_version=SIGNAL_CONTRACT,
            packet_type="signal_history",
            source=self.manifest.plugin_id,
            records=list(original.records),
            metadata={
                "replay_mode": "offline",
                "replay_path": str(path),
                "original_source": original.source,
                "original_created_at": original.created_at,
                "original_content_sha256": original.content_sha256,
                "original_metadata": original.metadata,
            },
        )


class SignalOutcomeEvaluator:
    """Evaluate fixed historical signals against an explicitly supplied price file."""

    manifest = PluginManifest(
        plugin_id="builtin.signal-outcome-evaluator",
        version="1.0.0",
        capability="evaluate.signal_outcomes",
        input_contracts=(SIGNAL_CONTRACT,),
        output_contract=OUTCOME_CONTRACT,
        permissions=frozenset({"filesystem:read"}),
        retry_safe=True,
    )

    ALLOWED_HORIZONS = {24, 72, 168}

    @staticmethod
    def _direction_correct(bias: str, return_decimal: float, neutral_band: float) -> bool | None:
        normalized = str(bias or "").strip().lower()
        if normalized in {"bullish", "slightly_bullish"}:
            return return_decimal > 0
        if normalized in {"bearish", "slightly_bearish"}:
            return return_decimal < 0
        if normalized == "neutral":
            return abs(return_decimal) <= neutral_band
        return None

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != SIGNAL_CONTRACT:
            raise PluginError(f"outcome evaluator requires {SIGNAL_CONTRACT}")
        if config.get("clock", "calendar_hours") != "calendar_hours":
            raise PluginError("this evaluator currently supports only clock=calendar_hours")
        if not config.get("prices_path"):
            raise PluginError("outcome evaluator requires config.prices_path")
        prices_path: Path = context.assert_read_path(str(config["prices_path"]))
        try:
            price_bytes = prices_path.read_bytes()
            raw_prices = json.loads(price_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PluginError(f"cannot read JSON file {prices_path}: {exc}") from exc
        if not isinstance(raw_prices, dict) or not isinstance(raw_prices.get("observations"), list):
            raise PluginError("price file must contain an observations array")
        default_price_source = str(raw_prices.get("price_source", "unknown"))

        observations: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for index, item in enumerate(raw_prices["observations"]):
            if not isinstance(item, dict):
                raise PluginError(f"price observation {index} must be an object")
            asset = str(item.get("asset", "")).upper()
            quote_asset = str(item.get("quote_asset", "")).upper()
            if not asset or not quote_asset:
                raise PluginError(f"price observation {index} is missing asset or quote_asset")
            try:
                observed_at = parse_aware_timestamp(item.get("observed_at"), "observed_at")
                price = float(item.get("price"))
            except (ContractError, TypeError, ValueError) as exc:
                raise PluginError(f"invalid price observation {index}: {exc}") from exc
            if price <= 0:
                raise PluginError(f"price observation {index} price must be positive")
            observations.setdefault((asset, quote_asset), []).append({
                "observed_at": observed_at,
                "observed_at_text": observed_at.isoformat(),
                "price": price,
                "source": str(item.get("source", default_price_source)),
            })
        for rows in observations.values():
            rows.sort(key=lambda row: row["observed_at"])

        raw_horizons = config.get("horizon_hours", [24, 72, 168])
        if not isinstance(raw_horizons, list) or not raw_horizons:
            raise PluginError("horizon_hours must be a non-empty array")
        horizons = [int(value) for value in raw_horizons]
        if any(value not in self.ALLOWED_HORIZONS for value in horizons):
            raise PluginError("horizon_hours may contain only 24, 72 and 168")
        if len(set(horizons)) != len(horizons):
            raise PluginError("horizon_hours must not contain duplicates")
        max_delay_hours = float(config.get("max_observation_delay_hours", 12))
        neutral_band = float(config.get("neutral_band_decimal", 0.002))
        if max_delay_hours < 0 or neutral_band < 0:
            raise PluginError("delay and neutral band must be non-negative")

        outcome_records: list[dict[str, Any]] = []
        for signal_index, signal in enumerate(packet.records):
            signal_id = str(signal.get("signal_id", ""))
            asset = str(signal.get("asset", "")).upper()
            quote_asset = str(signal.get("quote_asset", "")).upper()
            decision_text = signal.get("decision_at")
            reference_price = signal.get("reference_price")
            decision_at: datetime | None = None
            base_reason: str | None = None
            if not signal_id:
                base_reason = "missing_signal_id"
            elif not asset or not quote_asset:
                base_reason = "missing_asset_or_quote_asset"
            elif not decision_text:
                base_reason = "missing_decision_at"
            else:
                try:
                    decision_at = parse_aware_timestamp(decision_text, "decision_at")
                except ContractError:
                    base_reason = "invalid_or_naive_decision_at"
            try:
                entry_price = float(reference_price)
                if entry_price <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                entry_price = 0.0
                base_reason = base_reason or "missing_or_invalid_reference_price"

            price_rows = observations.get((asset, quote_asset), [])
            for horizon in horizons:
                common = {
                    "signal_id": signal_id,
                    "signal_index": signal_index,
                    "asset": asset,
                    "quote_asset": quote_asset,
                    "bias": signal.get("bias"),
                    "decision_at": decision_text,
                    "horizon_hours": horizon,
                    "clock": "calendar_hours",
                }
                if base_reason or decision_at is None:
                    outcome_records.append({**common, "status": "not_evaluable", "reason": base_reason})
                    continue
                target_at = decision_at + timedelta(hours=horizon)
                deadline = target_at + timedelta(hours=max_delay_hours)
                selected = next(
                    (row for row in price_rows if target_at <= row["observed_at"] <= deadline),
                    None,
                )
                if selected is None:
                    outcome_records.append({
                        **common,
                        "status": "not_evaluable",
                        "target_at": target_at.isoformat(),
                        "reason": "no_price_within_allowed_delay",
                    })
                    continue

                return_decimal = selected["price"] / entry_price - 1.0
                window = [
                    row for row in price_rows
                    if decision_at <= row["observed_at"] <= selected["observed_at"]
                ]
                window_returns = [row["price"] / entry_price - 1.0 for row in window]
                delay_hours = (selected["observed_at"] - target_at).total_seconds() / 3600
                quality_score = round(max(50.0, 100.0 - delay_hours * 4.0), 2)
                outcome_records.append({
                    **common,
                    "status": "evaluated",
                    "target_at": target_at.isoformat(),
                    "observed_at": selected["observed_at_text"],
                    "observation_delay_minutes": round(delay_hours * 60, 3),
                    "entry_price": entry_price,
                    "exit_price": selected["price"],
                    "return_decimal": round(return_decimal, 12),
                    "max_favorable_excursion_decimal": round(max(window_returns), 12),
                    "max_adverse_excursion_decimal": round(min(window_returns), 12),
                    "direction_correct": self._direction_correct(
                        str(signal.get("bias", "")), return_decimal, neutral_band
                    ),
                    "invalidated": None,
                    "price_source": selected["source"],
                    "data_quality_score": quality_score,
                })

        evaluated_count = sum(row["status"] == "evaluated" for row in outcome_records)
        return DataPacket.create(
            contract_version=OUTCOME_CONTRACT,
            packet_type="signal_outcomes",
            source=self.manifest.plugin_id,
            records=outcome_records,
            metadata={
                "input_sha256": packet.content_sha256,
                "input_source": packet.source,
                "prices_path": str(prices_path),
                "prices_sha256": hashlib.sha256(price_bytes).hexdigest(),
                "price_source": default_price_source,
                "horizon_hours": horizons,
                "clock": "calendar_hours",
                "max_observation_delay_hours": max_delay_hours,
                "evaluated_count": evaluated_count,
                "not_evaluable_count": len(outcome_records) - evaluated_count,
                "return_unit": "decimal",
            },
        )


class SqliteOutcomeWriter:
    """Idempotently backfill evaluated outcomes into an existing audit database."""

    manifest = PluginManifest(
        plugin_id="builtin.sqlite-outcome-writer",
        version="1.0.0",
        capability="sink.signal_outcomes",
        input_contracts=(OUTCOME_CONTRACT,),
        output_contract=OUTCOME_CONTRACT,
        permissions=frozenset({"filesystem:read", "filesystem:write"}),
        retry_safe=True,
    )

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != OUTCOME_CONTRACT:
            raise PluginError(f"SQLite outcome writer requires {OUTCOME_CONTRACT}")
        if not config.get("database_path"):
            raise PluginError("SQLite outcome writer requires config.database_path")
        apply = config.get("apply", False)
        if not isinstance(apply, bool):
            raise PluginError("SQLite outcome writer config.apply must be a boolean")
        evaluated = [row for row in packet.records if row.get("status") == "evaluated"]
        if not apply:
            receipt = {
                "status": "preview",
                "evaluated": len(evaluated),
                "inserted": 0,
                "existing": 0,
                "skipped": len(packet.records) - len(evaluated),
            }
            return DataPacket.create(
                contract_version=OUTCOME_CONTRACT,
                packet_type="signal_outcomes",
                source=self.manifest.plugin_id,
                records=list(packet.records),
                metadata={**packet.metadata, "backfill_receipt": receipt},
            )

        database_path: Path = context.assert_read_path(str(config["database_path"]))
        context.assert_write_path(str(database_path))
        if not database_path.is_file():
            raise PluginError(f"outcome database does not exist: {database_path}")
        inserted = 0
        existing = 0
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(database_path)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"daily_signals", "signal_outcomes"}.issubset(tables):
                raise PluginError("target database is missing daily_signals or signal_outcomes")
            for row in evaluated:
                signal_id = str(row.get("signal_id", ""))
                horizon = int(row.get("horizon_hours"))
                raw_json = canonical_json(row)
                prior = connection.execute(
                    "SELECT raw_json FROM signal_outcomes WHERE signal_id = ? AND horizon_hours = ?",
                    (signal_id, horizon),
                ).fetchone()
                if prior is not None:
                    if prior[0] != raw_json:
                        raise PluginError(
                            f"conflicting outcome already exists for {signal_id} at {horizon}h"
                        )
                    existing += 1
                    continue
                connection.execute(
                    """
                    INSERT INTO signal_outcomes (
                        signal_id, horizon_hours, observed_at, entry_price, exit_price,
                        return_pct, max_favorable_excursion_pct, max_adverse_excursion_pct,
                        direction_correct, price_source, data_quality_score, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal_id,
                        horizon,
                        row["observed_at"],
                        float(row["entry_price"]),
                        float(row["exit_price"]),
                        float(row["return_decimal"]) * 100.0,
                        float(row["max_favorable_excursion_decimal"]) * 100.0,
                        float(row["max_adverse_excursion_decimal"]) * 100.0,
                        None if row.get("direction_correct") is None else int(row["direction_correct"]),
                        str(row["price_source"]),
                        float(row["data_quality_score"]),
                        raw_json,
                    ),
                )
                inserted += 1
            connection.commit()
        except PluginError:
            if connection is not None:
                connection.rollback()
            raise
        except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            if connection is not None:
                connection.rollback()
            raise PluginError(f"failed to backfill signal outcomes: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        receipt = {
            "status": "applied",
            "database_path": str(database_path),
            "evaluated": len(evaluated),
            "inserted": inserted,
            "existing": existing,
            "skipped": len(packet.records) - len(evaluated),
        }
        return DataPacket.create(
            contract_version=OUTCOME_CONTRACT,
            packet_type="signal_outcomes",
            source=self.manifest.plugin_id,
            records=list(packet.records),
            metadata={**packet.metadata, "backfill_receipt": receipt},
        )


class OutcomeMarkdownReport:
    manifest = PluginManifest(
        plugin_id="builtin.markdown-outcome-report",
        version="1.0.0",
        capability="report.signal_outcomes",
        input_contracts=(OUTCOME_CONTRACT,),
        output_contract=REPORT_CONTRACT,
        permissions=frozenset({"filesystem:write"}),
        retry_safe=True,
    )

    @staticmethod
    def _cell(value: Any) -> str:
        return str(value if value is not None else "—").replace("|", "\\|").replace("\n", " ")

    def run(self, context: RunContext, packet: DataPacket | None, config: dict[str, Any]) -> DataPacket:
        if packet is None or packet.contract_version != OUTCOME_CONTRACT:
            raise PluginError(f"outcome report requires {OUTCOME_CONTRACT}")
        title = str(config.get("title", "QuantAgent 历史结果回填报告"))
        filename = str(config.get("filename", "outcome_report.md"))
        if Path(filename).name != filename or not filename.endswith(".md"):
            raise PluginError("outcome report filename must be a plain .md filename")
        evaluated = [row for row in packet.records if row.get("status") == "evaluated"]
        not_evaluable = [row for row in packet.records if row.get("status") != "evaluated"]
        receipt = packet.metadata.get("backfill_receipt", {"status": "not_requested"})
        lines = [
            f"# {title}",
            "",
            f"- Run ID: `{context.run_id}`",
            f"- 评价口径: `{packet.metadata.get('clock', 'unknown')}`",
            f"- 收益交换单位: `{packet.metadata.get('return_unit', 'unknown')}`",
            f"- 可评价: **{len(evaluated)}**",
            f"- 不可评价: **{len(not_evaluable)}**",
            f"- 数据库回填: `{receipt.get('status', 'unknown')}`",
            "",
            "## 结果",
            "",
            "| Signal | 期限 | 状态 | 收益 | 方向正确 | 实际取价时间 | 说明 |",
            "| --- | ---: | --- | ---: | --- | --- | --- |",
        ]
        for row in packet.records:
            if row.get("status") == "evaluated":
                return_text = f"{float(row['return_decimal']) * 100:+.2f}%"
                direction = row.get("direction_correct")
                direction_text = "是" if direction is True else "否" if direction is False else "无法评价"
                reason = ""
            else:
                return_text = "—"
                direction_text = "—"
                reason = row.get("reason", "unknown")
            lines.append(
                "| {signal} | {horizon}h | {status} | {ret} | {direction} | {observed} | {reason} |".format(
                    signal=self._cell(row.get("signal_id")),
                    horizon=self._cell(row.get("horizon_hours")),
                    status=self._cell(row.get("status")),
                    ret=self._cell(return_text),
                    direction=self._cell(direction_text),
                    observed=self._cell(row.get("observed_at")),
                    reason=self._cell(reason),
                )
            )
        lines.extend([
            "",
            "## 边界",
            "",
            "- 仅使用随运行显式提供的历史价格文件，不联网、不调用模型、不发送消息。",
            "- `decision_at` 必须由来源明确提供；不会用 `finalized_at` 冒充决策时间。",
            "- Crypto 期限按 24/72/168 自然小时计算；不适用于交易日市场。",
            "- 方向命中只评价判断方向，不代表扣除费用后的可交易收益。",
            "",
        ])
        content = "\n".join(lines)
        report_path = Path(context.run_dir) / filename
        try:
            report_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot write outcome report {report_path}: {exc}") from exc
        artifact_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return DataPacket.create(
            contract_version=REPORT_CONTRACT,
            packet_type="markdown_report",
            source=self.manifest.plugin_id,
            records=[{
                "path": str(report_path),
                "format": "markdown",
                "artifact_sha256": artifact_sha256,
                "input_sha256": packet.content_sha256,
            }],
            metadata={"artifact_count": 1, "title": title, "backfill_receipt": receipt},
        )
