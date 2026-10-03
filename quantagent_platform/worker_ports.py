"""Worker result and service port; concrete IO is bound only by trusted startup."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .plugins import RunContext


@dataclass(frozen=True)
class WorkerExecution:
    response: Any
    returncode: int
    stdout_sha256: str
    stderr_sha256: str


class WorkerServices(Protocol):
    def read_bounded(self, path: Path, max_bytes: int, label: str) -> bytes:
        ...

    def execute_json_worker(
        self, context: RunContext, *, display_name: str, file_prefix: str,
        python_executable: Path, worker_path: Path, request: dict[str, Any],
        timeout_seconds: float, max_response_bytes: int = 2 * 1024 * 1024,
        max_log_bytes: int = 64 * 1024,
    ) -> WorkerExecution:
        ...


_factory: Callable[[], WorkerServices] | None = None


def configure_worker_services(factory: Callable[[], WorkerServices]) -> None:
    """Bind a factory at trusted startup without constructing a service or doing IO."""
    if not callable(factory):
        raise TypeError("worker services factory must be callable")
    global _factory
    _factory = factory


def get_worker_services_factory() -> Callable[[], WorkerServices]:
    if _factory is None:
        raise RuntimeError("worker services factory has not been configured at startup")
    return _factory


def read_bounded(path: Path, max_bytes: int, label: str) -> bytes:
    return get_worker_services_factory()().read_bounded(path, max_bytes, label)


def execute_json_worker(
    context: RunContext,
    *,
    display_name: str,
    file_prefix: str,
    python_executable: Path,
    worker_path: Path,
    request: dict[str, Any],
    timeout_seconds: float,
    max_response_bytes: int = 2 * 1024 * 1024,
    max_log_bytes: int = 64 * 1024,
) -> WorkerExecution:
    return get_worker_services_factory()().execute_json_worker(
        context, display_name=display_name, file_prefix=file_prefix,
        python_executable=python_executable, worker_path=worker_path, request=request,
        timeout_seconds=timeout_seconds, max_response_bytes=max_response_bytes,
        max_log_bytes=max_log_bytes,
    )
