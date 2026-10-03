"""SDK-free recovery contracts; no persistence or execution at import time."""
from dataclasses import dataclass
from typing import Any, ContextManager, Literal, Protocol

JsonObject = dict[str, Any]
TaskKind = Literal["daily", "monitor"]
RecoveryAction = Literal["status", "retry", "confirm-sent", "confirm-not-sent", "abandon"]
SCHEMA_VERSION = 1


class RecoveryError(RuntimeError):
    """A recovery operation could not safely continue."""


class RecoveryInvalidState(RecoveryError):
    """Invalid, incompatible, or unresolved execution state."""


class RecoveryConflict(RecoveryError):
    """An immutable value or expected revision no longer matches."""


class RecoveryBusy(RecoveryError):
    """Another execution holds the required lock."""


@dataclass(frozen=True)
class FrozenSnapshot:
    version: int
    instance_id: str
    run_id: str
    kind: TaskKind
    date: str
    created_at: str
    payload_json: str
    sha256: str


@dataclass(frozen=True)
class RecoveryEvent:
    event_id: str
    step: str
    status: str
    occurred_at: str
    detail: JsonObject


@dataclass(frozen=True)
class ExecutionRecord:
    snapshot: FrozenSnapshot
    revision: int
    state: Literal["pending", "completed", "abandoned"]
    steps: dict[str, str]
    events: tuple[RecoveryEvent, ...]


@dataclass(frozen=True)
class StepResult:
    status: Literal["succeeded", "failed", "needs_review", "superseded"]
    detail: JsonObject


@dataclass(frozen=True)
class DeliveryResult:
    status: Literal["confirmed", "failed", "unknown", "not_configured"]
    source: Literal["provider", "legacy", "manual", "configuration"]
    channel_id: str | None
    error_code: str | None


class RecoveryStore(Protocol):
    @property
    def instance_id(self) -> str: ...
    def get(self, run_id: str) -> ExecutionRecord | None: ...
    def find_daily(self, date: str) -> ExecutionRecord | None: ...
    def list_open(self, kind: TaskKind | None = None) -> list[ExecutionRecord]: ...
    def create(self, snapshot: FrozenSnapshot) -> ExecutionRecord: ...
    def append_event(self, run_id: str, event: RecoveryEvent, *, expected_revision: int) -> ExecutionRecord: ...
    def lock(self, scope: Literal["daily", "monitor", "projection"]) -> ContextManager[None]: ...


class RecoveryStoreFactory(Protocol):
    def __call__(self, daily_dir: str, *, dry_run: bool = False) -> RecoveryStore: ...
