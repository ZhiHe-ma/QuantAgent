"""SQLite persistence boundary for QuantAgent Signal Audit.

This module deliberately has no dependency on agent_engine.py. Constructing a
store is side-effect free; the database is only opened by initialize(), write,
or query methods. A dry-run store never opens or creates the database.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


class SignalAuditError(RuntimeError):
    """Base error for audit persistence failures."""


class SignalAuditValidationError(SignalAuditError):
    """Raised before persistence when an audit record is incomplete."""


class SignalAuditStore:
    """Owns schema migration and atomic persistence of completed signals."""

    def __init__(
        self,
        db_path: str | Path,
        migration_dir: str | Path | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.db_path = Path(db_path)
        self.migration_dir = (
            Path(migration_dir)
            if migration_dir is not None
            else Path(__file__).resolve().parent / "sql"
        )
        self.dry_run = bool(dry_run)

    @staticmethod
    def new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _json(value: Any) -> str:
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise SignalAuditValidationError(f"value is not JSON serializable: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> dict[str, Any]:
        """Apply every forward-only migration; repeated calls are safe."""
        if self.dry_run:
            return {"status": "dry_run", "database_created": False}

        migrations = sorted(self.migration_dir.glob("[0-9][0-9][0-9]_*.sql"))
        if not migrations:
            raise SignalAuditError(f"no migrations found in {self.migration_dir}")

        connection: sqlite3.Connection | None = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            for migration in migrations:
                connection.executescript(migration.read_text(encoding="utf-8"))
        except (OSError, sqlite3.Error) as exc:
            raise SignalAuditError(f"failed to initialize audit database: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

        return {"status": "ready", "migrations_seen": len(migrations)}

    @staticmethod
    def _require(record: Mapping[str, Any], keys: Iterable[str], label: str) -> None:
        missing = [key for key in keys if record.get(key) in (None, "")]
        if missing:
            raise SignalAuditValidationError(
                f"{label} missing required fields: {', '.join(missing)}"
            )

    def _validate_records(
        self,
        run: Mapping[str, Any],
        signal: Mapping[str, Any],
        factors: list[Mapping[str, Any]],
    ) -> None:
        self._require(
            run,
            ("run_id", "trade_date", "started_at", "run_kind"),
            "run",
        )
        self._require(
            signal,
            (
                "signal_id",
                "signal_date",
                "asset",
                "risk_regime",
                "bias",
                "core_thesis",
                "invalid_if",
                "today_check",
                "analysis_text",
                "finalized_at",
            ),
            "signal",
        )
        if run.get("run_kind") not in {"scheduled", "forced", "reconciled"}:
            raise SignalAuditValidationError("run_kind is invalid")
        if signal["signal_date"] != run["trade_date"]:
            raise SignalAuditValidationError("signal_date must match run trade_date")
        for field, value in (
            ("started_at", run["started_at"]),
            ("completed_at", run.get("completed_at") or signal["finalized_at"]),
            ("finalized_at", signal["finalized_at"]),
        ):
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise SignalAuditValidationError(f"{field} must be ISO-8601") from exc
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise SignalAuditValidationError(f"{field} must include timezone")
        confidence = signal.get("confidence_raw")
        if not isinstance(confidence, int) or isinstance(confidence, bool):
            raise SignalAuditValidationError("confidence_raw must be an integer")
        if not 0 <= confidence <= 100:
            raise SignalAuditValidationError("confidence_raw must be between 0 and 100")
        quality = signal.get("data_quality_score")
        if not isinstance(quality, (int, float)) or isinstance(quality, bool):
            raise SignalAuditValidationError("data_quality_score must be numeric")
        if not 0 <= float(quality) <= 100:
            raise SignalAuditValidationError("data_quality_score must be between 0 and 100")
        if not isinstance(factors, list) or not all(isinstance(x, Mapping) for x in factors):
            raise SignalAuditValidationError("factors must be a list of mappings")

        # Force JSON validation before opening the database.
        for value in (
            signal.get("watch_items", []),
            signal.get("market_snapshot", {}),
            factors,
            signal.get("previous_memory", {}),
            signal.get("quality_flags", []),
        ):
            self._json(value)

    def record_completed_signal(
        self,
        run: Mapping[str, Any],
        signal: Mapping[str, Any],
        factors: Optional[list[Mapping[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Persist one completed run, its canonical signal, and factor rows atomically."""
        factor_rows = list(factors or [])
        self._validate_records(run, signal, factor_rows)

        if self.dry_run:
            return {
                "status": "dry_run",
                "run_id": run["run_id"],
                "signal_id": signal["signal_id"],
                "database_created": False,
            }

        connection: sqlite3.Connection | None = None
        try:
            self.initialize()
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT signal_id FROM daily_signals
                WHERE run_id = ? AND asset = ? AND decision_horizon = ?
                """,
                (
                    run["run_id"],
                    str(signal["asset"]).upper(),
                    signal.get("decision_horizon", "1d"),
                ),
            ).fetchone()
            if existing is not None:
                connection.rollback()
                return {
                    "status": "exists",
                    "run_id": run["run_id"],
                    "signal_id": existing["signal_id"],
                }

            completed_at = run.get("completed_at") or signal["finalized_at"]
            status = "reconciled" if run["run_kind"] == "reconciled" else "completed"
            existing_run = connection.execute(
                "SELECT trade_date FROM audit_runs WHERE run_id = ?",
                (run["run_id"],),
            ).fetchone()
            if existing_run is not None:
                if existing_run["trade_date"] != run["trade_date"]:
                    raise SignalAuditValidationError(
                        "existing run_id belongs to a different trade_date"
                    )
            else:
                connection.execute(
                    """
                    INSERT INTO audit_runs (
                        run_id, trade_date, started_at, completed_at, run_kind, status,
                        code_version, source_sha256, fast_model, reason_model,
                        report_written, wecom_sent, memory_saved
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run["run_id"],
                        run["trade_date"],
                        run["started_at"],
                        completed_at,
                        run["run_kind"],
                        status,
                        run.get("code_version"),
                        run.get("source_sha256"),
                        run.get("fast_model"),
                        run.get("reason_model"),
                        int(bool(run.get("report_written", True))),
                        int(bool(run.get("wecom_sent", True))),
                        int(bool(run.get("memory_saved", True))),
                    ),
                )

            asset = str(signal["asset"]).upper()
            horizon = signal.get("decision_horizon", "1d")
            connection.execute(
                """
                UPDATE daily_signals SET is_canonical = 0
                WHERE signal_date = ? AND asset = ?
                  AND decision_horizon = ? AND is_canonical = 1
                """,
                (signal["signal_date"], asset, horizon),
            )
            connection.execute(
                """
                INSERT INTO daily_signals (
                    signal_id, run_id, signal_date, asset, quote_asset,
                    decision_horizon, risk_regime, bias, confidence_raw,
                    confidence_calibrated, core_thesis, invalid_if, today_check,
                    watch_items_json, reference_price, market_snapshot_json,
                    factors_json, previous_memory_json, analysis_text, factor_count,
                    data_quality_score, quality_flags_json, is_canonical, finalized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, 1, ?)
                """,
                (
                    signal["signal_id"],
                    run["run_id"],
                    signal["signal_date"],
                    asset,
                    signal.get("quote_asset", "USDT"),
                    horizon,
                    signal["risk_regime"],
                    signal["bias"],
                    signal["confidence_raw"],
                    signal.get("confidence_calibrated"),
                    signal["core_thesis"],
                    signal["invalid_if"],
                    signal["today_check"],
                    self._json(signal.get("watch_items", [])),
                    signal.get("reference_price"),
                    self._json(signal.get("market_snapshot", {})),
                    self._json(factor_rows),
                    self._json(signal.get("previous_memory", {})),
                    signal["analysis_text"],
                    len(factor_rows),
                    float(signal["data_quality_score"]),
                    self._json(signal.get("quality_flags", [])),
                    signal["finalized_at"],
                ),
            )

            for ordinal, factor in enumerate(factor_rows):
                connection.execute(
                    """
                    INSERT INTO signal_factors (
                        signal_id, ordinal, event_time, source, title, sentiment,
                        weight, reason, fingerprint, raw_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal["signal_id"],
                        ordinal,
                        factor.get("time"),
                        str(factor.get("source", "")),
                        str(factor.get("title", "")),
                        str(factor.get("sentiment", "中性")),
                        str(factor.get("weight", "Low")),
                        str(factor.get("reason", "")),
                        factor.get("fingerprint"),
                        self._json(factor),
                    ),
                )

            connection.commit()
            return {
                "status": "recorded",
                "run_id": run["run_id"],
                "signal_id": signal["signal_id"],
            }
        except SignalAuditError:
            if connection is not None:
                connection.rollback()
            raise
        except (sqlite3.Error, OSError, SignalAuditValidationError) as exc:
            if connection is not None:
                connection.rollback()
            raise SignalAuditError(f"failed to record completed signal: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()

    def get_canonical_signal(
        self,
        signal_date: str,
        asset: str = "BTC",
        decision_horizon: str = "1d",
    ) -> Optional[dict[str, Any]]:
        if self.dry_run or not self.db_path.exists():
            return None
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect()
            row = connection.execute(
                """
                SELECT * FROM daily_signals
                WHERE signal_date = ? AND asset = ?
                  AND decision_horizon = ? AND is_canonical = 1
                """,
                (signal_date, asset.upper(), decision_horizon),
            ).fetchone()
        except sqlite3.Error as exc:
            raise SignalAuditError(f"failed to read canonical signal: {exc}") from exc
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        result = dict(row)
        for key in (
            "watch_items_json",
            "market_snapshot_json",
            "factors_json",
            "previous_memory_json",
            "quality_flags_json",
        ):
            result[key.removesuffix("_json")] = json.loads(result[key])
        return result


def calculate_data_quality(
    market_snapshot: Mapping[str, Any],
    factors: list[Mapping[str, Any]],
    *,
    version_known: bool,
    reconciled: bool = False,
) -> tuple[float, list[str]]:
    """Return the deterministic v1 completeness score and its audit flags."""
    score = 100.0
    flags: list[str] = []
    crypto = market_snapshot.get("crypto", {}) or {}
    macro = market_snapshot.get("macro", {}) or {}

    def missing(value: Any) -> bool:
        return value in (None, "", "暂无数据")

    deductions = (
        (missing(crypto.get("BTC_Price")), 35, "missing_reference_price"),
        (missing(macro.get("S&P500_Chg%")), 10, "missing_sp500"),
        (missing(macro.get("VIX_Volatility")), 10, "missing_vix"),
        (missing(crypto.get("Fear_Greed")), 5, "missing_fear_greed"),
        (not factors, 10, "no_model_factors"),
        (not version_known, 10, "unknown_code_or_model_version"),
        (reconciled, 10, "reconciled_record"),
    )
    for condition, points, flag in deductions:
        if condition:
            score -= points
            flags.append(flag)
    return max(0.0, score), flags
