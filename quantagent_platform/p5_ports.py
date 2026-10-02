"""P5 evidence data, pure admission rules and startup-injected storage ports."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
from typing import Any, ContextManager, Protocol, Sequence

from .contracts import DataPacket


class ApprovedSourceError(ValueError):
    """Private approved source is missing, unsafe, or inconsistent."""


class LedgerError(RuntimeError):
    """P5 chain state is invalid or cannot be persisted."""


class HandoffError(ValueError):
    """A fixed SEC route or handoff failed admission."""


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise LedgerError(f"{label} must be a safe bounded identifier")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ApprovedSourceError("approved JSON has duplicate keys")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ApprovedSourceError("approved JSON has a non-finite number")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ApprovedSourceError("approved JSON has a non-finite number")
    return parsed


def strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedSourceError("approved JSON is not strict UTF-8") from exc
    if not isinstance(value, dict):
        raise ApprovedSourceError("approved JSON root must be an object")
    return value


@dataclass(frozen=True)
class ApprovedRun:
    source_id: str
    run_id: str
    run_dir: Path
    registry_sha256: str
    packet_sha256: str
    report_sha256: str
    raw_sha256: dict[str, str]
    recipe_id: str
    recipe_version: str
    source_plugin_id: str
    source_plugin_version: str

    @classmethod
    def from_pins(cls, pins: dict[str, object], run_root: Path) -> "ApprovedRun":
        """Compatibility factory; the storage owner validates paths and pins."""
        return get_p5_services().source_from_pins(pins, run_root, cls)

    def to_pins(self) -> dict[str, object]:
        return {
            "approved_source_id": self.source_id,
            "run_id": self.run_id,
            "recipe": {"id": self.recipe_id, "version": self.recipe_version},
            "source_plugin": {
                "id": self.source_plugin_id, "version": self.source_plugin_version
            },
            "packet_sha256": self.packet_sha256,
            "report_sha256": self.report_sha256,
            "raw_sha256": dict(self.raw_sha256),
            "registry_sha256": self.registry_sha256,
        }


@dataclass(frozen=True)
class SecEvidence:
    packet: DataPacket
    record_sha256: str
    packet_file_sha256: str
    sector_packet: DataPacket
    peer_packet: DataPacket
    report_packet: DataPacket
    report: bytes
    report_sha256: str
    raw: dict[str, bytes]
    raw_sha256: dict[str, str]


class ResolvedPlanView(Protocol):
    """Only the public plan data used by fixed-route admission."""
    catalog: Any
    agent_entry: Any
    skill_entry: Any
    recipe_entry: Any
    agent: dict[str, Any]
    skill: dict[str, Any]
    resolved_plugins: Sequence[tuple[dict[str, Any], Any]]


class ParentRunView(Protocol):
    run_id: str
    status: str
    final_packet: DataPacket
    steps: tuple[dict[str, Any], ...]


class ApprovedRegistry(Protocol):
    def resolve(self, source_id: str) -> ApprovedRun: ...


class Ledger(Protocol):
    @property
    def root(self) -> Path: ...
    def reserve(self, request_id: str, fingerprint: str) -> tuple[str, bool]: ...
    def transition(self, chain_id: str, status: str, **fields: Any) -> dict[str, Any]: ...
    def get(self, chain_id: str) -> dict[str, Any]: ...
    def recover_interrupted(self) -> int: ...


class P5Services(Protocol):
    """Owned P5 IO only; no profiles, rule updates or network/model capabilities."""
    def read_file(self, path: Path, limit: int) -> bytes: ...
    def path_signatures(self, path: Path) -> tuple[tuple[Path, tuple[int, int, int]], ...]: ...
    def same_directory(self, left: Path, right: Path) -> bool: ...
    def approved_registry(self, path: Path, run_root: Path) -> ApprovedRegistry: ...
    def source_from_pins(self, pins: dict[str, object], run_root: Path,
                         source_type: type[ApprovedRun] = ApprovedRun) -> ApprovedRun: ...
    def read_approved_source(self, source: ApprovedRun) -> SecEvidence: ...
    def new_ledger(self, root: Path) -> Ledger: ...
    def handoff_schema(self) -> dict[str, Any]: ...
    def prepare_run_root(self, path: Path) -> Path: ...
    def prepare_broker_directory(self, path: Path) -> None: ...
    def controller_lock(self, root: Path) -> ContextManager[None]: ...
    def atomic_bytes(self, path: Path, raw: bytes) -> None: ...


_services: P5Services | None = None


def configure_p5_services(services: P5Services) -> None:
    """Startup configuration; binding an implementation does not perform IO."""
    if services is None:
        raise TypeError("P5 services must implement the storage port")
    global _services
    _services = services


def get_p5_services() -> P5Services:
    if _services is None:
        raise RuntimeError("P5 storage services have not been configured at startup")
    return _services
