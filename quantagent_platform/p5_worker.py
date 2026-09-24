"""Spawn one fixed offline Agent in a deadline-bound, verified process."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from .contracts import ContractError, DataPacket, canonical_json
from .p5_registry import ApprovedSourceError, bounded_regular_file, strict_json


_MAX_SPEC = 64 * 1024
_MAX_RESULT = 4 * 1024
_MAX_PACKET = 2 * 1024 * 1024
_ROLES = {
    "builtin.sec-evidence-producer-agent": (
        "builtin.sec-evidence-preparation", "sec-evidence-producer",
        {"registry_path", "approved_run_root", "approved_source_id"},
        "02-prepare-sec-evidence.json", "quantagent.sec_evidence_bundle.v1",
        "builtin.sec-evidence-preparer",
    ),
    "builtin.sec-evidence-review-agent": (
        "builtin.sec-evidence-independent-review", "sec-evidence-review",
        {"handoff_path", "handoff_sha256", "bundle_path", "approved_run_root"},
        "03-write-sec-review.json", "quantagent.report.v1",
        "builtin.markdown-sec-independent-review",
    ),
}


@dataclass(frozen=True)
class WorkerSpec:
    agent_id: str
    agent_version: str
    skill_id: str
    skill_version: str
    recipe_id: str
    recipe_version: str
    params: dict[str, str]
    run_id: str
    output_root: str
    read_roots: list[str]
    write_roots: list[str]
    permissions: list[str]
    submission_context: dict[str, str]

    def __post_init__(self) -> None:
        from .p5_ledger import _safe_id

        role = _ROLES.get(self.agent_id)
        if role is None or (
            self.agent_version, self.skill_id, self.skill_version,
            self.recipe_id, self.recipe_version,
        ) != ("1.0.0", role[0], "1.0.0", role[1], "1.0.0"):
            raise ValueError("worker Agent/Skill/Recipe is outside fixed P5 route")
        try:
            _safe_id(self.run_id, "run_id")
        except ValueError as exc:
            raise ValueError("worker run ID is invalid") from exc
        if (
            not isinstance(self.params, dict)
            or set(self.params) != role[2]
            or any(not isinstance(value, str) or not value for value in self.params.values())
            or not isinstance(self.output_root, str)
            or not self.output_root
            or not isinstance(self.read_roots, list)
            or not self.read_roots
            or any(not isinstance(value, str) or not value for value in self.read_roots)
            or not isinstance(self.write_roots, list)
            or any(not isinstance(value, str) or not value for value in self.write_roots)
            or self.permissions != ["filesystem:read", "filesystem:write"]
            or not isinstance(self.submission_context, dict)
            or not set(self.submission_context) <= {
                "coordinator_id", "request_id", "policy_sha256", "handoff_sha256",
            }
            or any(not isinstance(value, str) or not value
                   for value in self.submission_context.values())
        ):
            raise ValueError("worker parameters are outside fixed P5 route")
        try:
            raw = canonical_json(asdict(self)).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("worker spec is not JSON-safe") from exc
        if len(raw) > _MAX_SPEC:
            raise ValueError("worker spec exceeds 64 KiB")

    def to_bytes(self) -> bytes:
        return canonical_json(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> "WorkerSpec":
        if not isinstance(raw, bytes) or len(raw) > _MAX_SPEC:
            raise ValueError("worker spec is too large")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
                raise ValueError("worker spec fields differ")
            return cls(**value)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("worker spec JSON is invalid") from exc


@dataclass(frozen=True)
class WorkerResult:
    status: str
    run_id: str
    packet_path: Path | None = None
    packet_sha256: str | None = None
    content_sha256: str | None = None


def _send(connection, value: dict[str, Any]) -> None:
    raw = canonical_json(value).encode("utf-8")
    if len(raw) <= _MAX_RESULT:
        connection.send_bytes(raw)


def _agent_worker(connection, cancel_flag, spec_raw: bytes) -> None:
    try:
        spec = WorkerSpec.from_bytes(spec_raw)
        from .agents import AgentRuntime
        from .runner import RunCancelled

        try:
            result = AgentRuntime().run(
                agent_id=spec.agent_id, agent_version=spec.agent_version,
                skill_id=spec.skill_id, skill_version=spec.skill_version,
                recipe_id=spec.recipe_id, recipe_version=spec.recipe_version,
                params=spec.params, output_dir=spec.output_root,
                allowed_read_roots=spec.read_roots,
                allowed_write_roots=spec.write_roots,
                allowed_permissions=set(spec.permissions), offline=True,
                run_id=spec.run_id,
                submission_context=spec.submission_context,
                cancel_check=cancel_flag.is_set,
            )
        except RunCancelled:
            _send(connection, {"status": "cancelled", "run_id": spec.run_id})
            return
        except Exception:
            _send(connection, {"status": "failed", "run_id": spec.run_id})
            return
        if result.status != "completed" or not result.steps:
            _send(connection, {"status": "failed", "run_id": spec.run_id})
            return
        path = Path(result.steps[-1]["packet_path"])
        raw = bounded_regular_file(path, _MAX_PACKET)
        _send(connection, {
            "status": "completed", "run_id": spec.run_id,
            "packet_path": str(path),
            "packet_sha256": hashlib.sha256(raw).hexdigest(),
            "content_sha256": result.final_packet.content_sha256,
        })
    finally:
        connection.close()


class WorkerSupervisor:
    def __init__(self, *, _test_entrypoint: Callable | None = None) -> None:
        self._entrypoint = _agent_worker if _test_entrypoint is None else _test_entrypoint

    @staticmethod
    def _verified_result(spec: WorkerSpec, response: dict[str, Any]) -> WorkerResult:
        if not isinstance(response, dict) or response.get("run_id") != spec.run_id:
            return WorkerResult("interrupted", spec.run_id)
        status = response.get("status")
        if status in {"failed", "cancelled"} and set(response) == {"status", "run_id"}:
            return WorkerResult(status, spec.run_id)
        if status != "completed" or set(response) != {
            "status", "run_id", "packet_path", "packet_sha256", "content_sha256",
        }:
            return WorkerResult("interrupted", spec.run_id)
        if (
            not isinstance(response["packet_path"], str)
            or not response["packet_path"]
            or not isinstance(response["packet_sha256"], str)
            or not isinstance(response["content_sha256"], str)
        ):
            return WorkerResult("interrupted", spec.run_id)
        role = _ROLES[spec.agent_id]
        expected_dir = Path(os.path.abspath(spec.output_root)) / spec.run_id
        path = Path(response["packet_path"])
        if Path(os.path.abspath(path)).parent != expected_dir or path.name != role[3]:
            return WorkerResult("interrupted", spec.run_id)
        try:
            raw = bounded_regular_file(path, _MAX_PACKET)
            packet = DataPacket.from_dict(strict_json(raw))
            if (
                packet.contract_version != role[4]
                or packet.source != role[5]
                or packet.content_sha256 != response["content_sha256"]
                or hashlib.sha256(raw).hexdigest() != response["packet_sha256"]
            ):
                return WorkerResult("interrupted", spec.run_id)
        except (ApprovedSourceError, ContractError, OSError, TypeError, ValueError):
            return WorkerResult("interrupted", spec.run_id)
        return WorkerResult(
            "completed", spec.run_id, path,
            response["packet_sha256"], response["content_sha256"],
        )

    def run(self, spec: WorkerSpec, deadline: float, cancel_event) -> WorkerResult:
        if not isinstance(spec, WorkerSpec) or not isinstance(deadline, (float, int)):
            raise ValueError("worker requires a fixed spec and monotonic deadline")
        if cancel_event.is_set():
            return WorkerResult("cancelled", spec.run_id)
        if time.monotonic() >= deadline:
            return WorkerResult("timed_out", spec.run_id)
        context = multiprocessing.get_context("spawn")
        parent_pipe, child_pipe = context.Pipe(duplex=False)
        child_cancel = context.Event()
        process = context.Process(
            target=self._entrypoint,
            args=(child_pipe, child_cancel, spec.to_bytes()),
        )
        try:
            try:
                process.start()
            except (OSError, RuntimeError):
                return WorkerResult("interrupted", spec.run_id)
            child_pipe.close()
            response: dict[str, Any] | None = None
            reason: str | None = None
            cancel_until: float | None = None
            while True:
                try:
                    if parent_pipe.poll(0.02):
                        raw = parent_pipe.recv_bytes(_MAX_RESULT)
                        response = strict_json(raw)
                        break
                except (EOFError, OSError, ApprovedSourceError):
                    break
                if not process.is_alive():
                    break
                now = time.monotonic()
                if cancel_event.is_set() and cancel_until is None:
                    child_cancel.set()
                    cancel_until = min(deadline, now + 5)
                if now >= deadline:
                    reason = "cancelled" if cancel_until is not None else "timed_out"
                    break
                if cancel_until is not None and now >= cancel_until:
                    reason = "cancelled"
                    break
            if reason is not None:
                process.terminate()
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
                return WorkerResult(reason, spec.run_id)
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
            if process.exitcode not in (0, None) or response is None:
                return WorkerResult("interrupted", spec.run_id)
            if time.monotonic() >= deadline:
                return WorkerResult("timed_out", spec.run_id)
            return self._verified_result(spec, response)
        finally:
            child_pipe.close()
            try:
                if process.pid is not None and process.is_alive():
                    # Also runs when Ctrl+C interrupts the supervisor loop. Let
                    # a cooperative worker stop before forcing termination.
                    child_cancel.set()
                    process.join(timeout=5)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=5)
            finally:
                parent_pipe.close()


def run_worker(spec: WorkerSpec, deadline: float, cancel_event) -> WorkerResult:
    """Production entrypoint: only the fixed module-level Agent worker is used."""
    return WorkerSupervisor().run(spec, deadline, cancel_event)
