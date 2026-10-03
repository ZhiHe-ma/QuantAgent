"""Explicit workflow callbacks and a lazy, trusted legacy audit binding."""
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol
from signal_audit_contracts import SignalAuditError


class AuditStore(Protocol):
    def record_completed_signal(self, run: Any, signal: Any, factors: Any = None) -> dict[str, Any]: ...


class AuditStoreFactory(Protocol):
    def __call__(self, db_path: str | Path, migration_dir: str | Path | None = None,
                 *, dry_run: bool = False) -> AuditStore: ...
    def new_id(self, prefix: str) -> str: ...


@dataclass(frozen=True)
class LegacyAuditBindings:
    store_factory: AuditStoreFactory
    calculate_data_quality: Callable[..., tuple[float, list[str]]]


_audit_factory: Callable[[], LegacyAuditBindings] | None = None


def configure_legacy_audit_factory(factory: Callable[[], LegacyAuditBindings]) -> None:
    """Bind at trusted process startup, without constructing a store or invoking IO."""
    if not callable(factory):
        raise TypeError("legacy audit factory must be callable")
    global _audit_factory
    _audit_factory = factory


def get_legacy_audit_factory() -> Callable[[], LegacyAuditBindings]:
    if _audit_factory is None:
        raise RuntimeError("legacy audit factory has not been configured at startup")
    return _audit_factory


def get_legacy_audit_bindings() -> LegacyAuditBindings:
    bindings = get_legacy_audit_factory()()
    if not isinstance(bindings, LegacyAuditBindings) or not callable(bindings.store_factory) \
            or not callable(getattr(bindings.store_factory, "new_id", None)) \
            or not callable(bindings.calculate_data_quality):
        raise TypeError("legacy audit factory must return valid LegacyAuditBindings")
    return bindings


@dataclass(frozen=True)
class MonitorPorts:
    dedup_file: str
    fingerprint_file: str
    failed_news_file: str
    max_news_per_cycle: int
    max_news_ai_retries: int
    min_store_weight: str
    read_json: Callable[[str, Any], Any]
    write_json: Callable[[str, Any], bool]
    get_buffer_path: Callable[[], str]
    fetch_crypto_flash_news: Callable[[], list[dict[str, Any]]]
    news_fingerprint: Callable[[dict[str, Any]], str]
    clamp_str: Callable[..., str]
    strip_json_fence: Callable[[str], str]
    request_deepseek: Callable[..., str]
    calibrate_factor_weight: Callable[..., tuple[str, str]]
    weight_rank: Callable[[str], int]
    prune_day_buffer: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    now: Callable[[], datetime]
    sleep: Callable[[float], None]


@dataclass(frozen=True)
class DailyPorts:
    dry_run: bool
    force_daily_run: bool
    load_memory_state: Callable[[], dict[str, Any]]
    report_path: Callable[[str], str]
    report_exists: Callable[[str], bool]
    clamp_str: Callable[..., str]
    fetch_market_signals: Callable[[], dict[str, Any]]
    get_buffer_path: Callable[[], str]
    read_json: Callable[[str, Any], Any]
    compact_news_factors: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    clamp_memory_state: Callable[[dict[str, Any]], dict[str, Any]]
    request_deepseek: Callable[..., str]
    generate_memory_capsule: Callable[..., dict[str, Any]]
    record_signal_audit: Callable[..., dict[str, Any]]
    write_report: Callable[[str, str], None]
    push_to_wecom: Callable[[str], bool]
    save_memory_capsule: Callable[[dict[str, Any]], bool]
    now: Callable[[], datetime]
