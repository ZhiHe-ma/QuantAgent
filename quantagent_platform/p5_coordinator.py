"""Single-hop, offline SEC Agent coordination with private audit state."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .agents import AgentRuntime
from .contracts import ContractError, DataPacket, sha256_json, utc_now
from .p5_handoff import (
    CHILD_ID, PARENT_ID, TASK_TYPE, HandoffError, RoutePolicy,
    create_handoff, preflight_route, verify_handoff,
)
from .p5_ledger import HandoffLedger, LedgerError
from .p5_registry import (
    ApprovedRunRegistry, ApprovedSourceError, bounded_regular_file, strict_json,
)
from .p5_worker import WorkerResult, WorkerSpec, run_worker
from .runner import RunResult


_BUNDLE = "quantagent.sec_evidence_bundle.v1"
_REPORT = "quantagent.report.v1"
_MAX_STATE = 512 * 1024
_MAX_PACKET = 2 * 1024 * 1024
_MAX_REPORT = 512 * 1024
_PERMISSIONS = frozenset({"filesystem:read", "filesystem:write"})
_TERMINAL_MAP = {
    "failed": "failed", "timed_out": "timed_out",
    "cancelled": "cancelled", "interrupted": "interrupted",
}
_FAILURE_CODE = {
    "failed": {"parent": "parent_failed", "child": "child_failed"},
    "timed_out": {"parent": "deadline_exceeded", "child": "deadline_exceeded"},
    "cancelled": {"parent": "cancel_requested", "child": "cancel_requested"},
    "interrupted": {"parent": "process_interrupted", "child": "process_interrupted"},
}


@contextmanager
def _exclusive_controller(root: Path):
    """One P5 controller at a time, including crash recovery and dispatch."""
    lock_path = root / ".p5_controller.lock"
    if lock_path.is_symlink() or lock_path.is_junction():
        raise HandoffError("P5 controller lock path is a link")
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            until = time.monotonic() + 130
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if time.monotonic() >= until:
                        raise HandoffError("P5 controller lock is busy") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _atomic_bytes(path: Path, raw: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


@dataclass(frozen=True)
class ChainResult:
    chain_id: str
    status: str
    parent_run_id: str | None
    child_run_id: str | None
    handoff_sha256: str | None
    wall_ms: int | None
    handoff_calls: int
    model_cost_minor: int
    failure_code: str | None

    @classmethod
    def from_ledger(cls, record: dict[str, Any]) -> "ChainResult":
        return cls(
            chain_id=record["chain_id"], status=record["status"],
            parent_run_id=record["parent_id"], child_run_id=record["child_id"],
            handoff_sha256=record["handoff_sha256"], wall_ms=record["wall_ms"],
            handoff_calls=record["handoff_calls"],
            model_cost_minor=record["model_cost_minor"],
            failure_code=record["failure_code"],
        )


class P5Coordinator:
    def __init__(
        self, registry_path: Path, approved_run_root: Path, run_root: Path,
        policy_path: Path, ledger: HandoffLedger | None = None,
        worker: Callable[[WorkerSpec, float, Any], WorkerResult] = run_worker,
        caller_permissions: frozenset[str] = _PERMISSIONS,
        cancel_event: Any | None = None,
    ) -> None:
        self.registry_path = Path(registry_path)
        self.approved_run_root = Path(approved_run_root)
        self.run_root = Path(run_root).expanduser().resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.policy_path = Path(policy_path)
        self.ledger = ledger or HandoffLedger(self.run_root)
        if self.ledger.root != self.run_root:
            raise HandoffError("P5 ledger root differs from run root")
        self.worker = worker
        self.caller_permissions = frozenset(caller_permissions)
        self.cancel_event = cancel_event or threading.Event()

    def _elapsed_ms(self, started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    def _terminal(self, chain_id: str, phase: str, status: str,
                  started: float) -> ChainResult:
        outcome = _TERMINAL_MAP.get(status, "failed")
        code = _FAILURE_CODE.get(status, _FAILURE_CODE["failed"])[phase]
        self.ledger.transition(
            chain_id, outcome, failure_code=code,
            wall_ms=self._elapsed_ms(started),
        )
        return ChainResult.from_ledger(self.ledger.get(chain_id))

    def _checked_packet(self, result: WorkerResult, run_id: str,
                        name: str, contract: str, source: str) -> tuple[DataPacket, bytes]:
        if (
            not isinstance(result, WorkerResult)
            or result.status != "completed"
            or result.run_id != run_id
            or result.packet_path is None
            or result.packet_sha256 is None
            or result.content_sha256 is None
        ):
            raise HandoffError("Agent worker returned no completed packet")
        path = Path(result.packet_path)
        if (Path(os.path.abspath(path)).parent != self.run_root / run_id
                or path.name != name):
            raise HandoffError("Agent packet path differs from fixed run")
        try:
            raw = bounded_regular_file(path, _MAX_PACKET)
            packet = DataPacket.from_dict(strict_json(raw))
        except (ApprovedSourceError, ContractError, TypeError) as exc:
            raise HandoffError("Agent packet cannot be verified") from exc
        if (
            hashlib.sha256(raw).hexdigest() != result.packet_sha256
            or packet.content_sha256 != result.content_sha256
            or packet.contract_version != contract
            or packet.source != source
            or len(packet.records) != 1
        ):
            raise HandoffError("Agent packet hash or contract differs")
        return packet, raw

    def _checked_state(self, run_id: str, agent_id: str,
                       final_packet: DataPacket, chain_id: str) -> dict[str, Any]:
        try:
            state = strict_json(bounded_regular_file(
                self.run_root / run_id / "run.json", _MAX_STATE))
            invocation = state["invocation"]
            steps = state["steps"]
            if (
                state["run_id"] != run_id
                or state["status"] != "completed"
                or state["offline"] is not True
                or state["final_contract"] != final_packet.contract_version
                or state["final_sha256"] != final_packet.content_sha256
                or invocation["agent"]["id"] != agent_id
                or invocation["submission"]["coordinator_id"] != chain_id
                or invocation["catalog"]["sha256"] != self._catalog_sha256
                or not isinstance(steps, list)
                or len(steps) != (2 if agent_id == PARENT_ID else 3)
                or steps[-1]["output_sha256"] != final_packet.content_sha256
                or steps[-1]["status"] != "completed"
            ):
                raise HandoffError("Agent run state differs from fixed invocation")
            return state
        except (ApprovedSourceError, KeyError, TypeError, IndexError) as exc:
            raise HandoffError("Agent run state cannot be verified") from exc

    def _spec(self, *, agent_id: str, chain_id: str, request_id: str,
              run_id: str, params: dict[str, str], policy_sha256: str,
              broker_dir: Path | None = None, handoff_sha256: str | None = None,
              ) -> WorkerSpec:
        parent = agent_id == PARENT_ID
        read_roots = (
            [str(self.registry_path.parent), str(self.approved_run_root)]
            if parent else [str(self.approved_run_root), str(broker_dir)]
        )
        return WorkerSpec(
            agent_id=agent_id, agent_version="1.0.0",
            skill_id=("builtin.sec-evidence-preparation" if parent else
                      "builtin.sec-evidence-independent-review"),
            skill_version="1.0.0",
            recipe_id="sec-evidence-producer" if parent else "sec-evidence-review",
            recipe_version="1.0.0", params=params,
            run_id=run_id, output_root=str(self.run_root),
            read_roots=read_roots,
            write_roots=[str(self.run_root / run_id)],
            permissions=sorted(_PERMISSIONS),
            submission_context={
                "coordinator_id": chain_id,
                "request_id": request_id,
                "policy_sha256": policy_sha256,
                **({"handoff_sha256": handoff_sha256} if handoff_sha256 else {}),
            },
        )

    def run(self, source_id: str, request_id: str) -> ChainResult:
        """Execute one approved SEC source against the only allowed reviewer."""
        with _exclusive_controller(self.run_root):
            self.ledger.recover_interrupted()
            return self._run_locked(source_id, request_id)

    def _run_locked(self, source_id: str, request_id: str) -> ChainResult:
        registry = ApprovedRunRegistry.load(
            self.registry_path, self.approved_run_root)
        source = registry.resolve(source_id)
        policy = RoutePolicy.load(self.policy_path)
        runtime = AgentRuntime()
        parent_plan = runtime.resolve(
            agent_id=PARENT_ID, agent_version="1.0.0", offline=True,
        )
        child_plan = runtime.resolve(
            agent_id=CHILD_ID, agent_version="1.0.0", offline=True,
        )
        effective = preflight_route(
            policy, parent_plan, child_plan, self.caller_permissions)
        self._catalog_sha256 = runtime.catalog.sha256
        fingerprint = sha256_json({
            "approved_source_id": source_id,
            "packet_sha256": source.packet_sha256,
            "task_type": TASK_TYPE,
            "route_policy_sha256": policy.sha256,
        })
        chain_id, created = self.ledger.reserve(request_id, fingerprint)
        if not created:
            return ChainResult.from_ledger(self.ledger.get(chain_id))
        started = time.monotonic()
        deadline = started + policy.data["limits"]["max_wall_seconds"]
        parent_id = "p5p-" + chain_id[3:]
        child_id = "p5c-" + chain_id[3:]
        phase = "parent"
        try:
            self.ledger.transition(
                chain_id, "parent_running", parent_id=parent_id,
                source_packet_sha256=source.packet_sha256,
                source_report_sha256=source.report_sha256,
                raw_hashes_json=source.raw_sha256,
                catalog_sha256=runtime.catalog.sha256,
                policy_sha256=policy.sha256,
                permissions_json=sorted(effective),
            )
            parent_spec = self._spec(
                agent_id=PARENT_ID, chain_id=chain_id,
                request_id=request_id, run_id=parent_id,
                params={
                    "registry_path": str(self.registry_path),
                    "approved_run_root": str(self.approved_run_root),
                    "approved_source_id": source.source_id,
                }, policy_sha256=policy.sha256,
            )
            parent_worker = self.worker(parent_spec, deadline, self.cancel_event)
            if parent_worker.status != "completed":
                return self._terminal(chain_id, phase, parent_worker.status, started)
            parent_packet, parent_bytes = self._checked_packet(
                parent_worker, parent_id, "02-prepare-sec-evidence.json",
                _BUNDLE, "builtin.sec-evidence-preparer",
            )
            parent_state = self._checked_state(
                parent_id, PARENT_ID, parent_packet, chain_id)
            parent_result = RunResult(
                run_id=parent_id, status="completed",
                run_dir=self.run_root / parent_id,
                final_packet=parent_packet,
                steps=tuple(parent_state["steps"]),
            )
            self.ledger.transition(
                chain_id, "parent_completed",
                bundle_sha256=hashlib.sha256(parent_bytes).hexdigest(),
            )
            broker_dir = self.run_root / ".p5_broker" / chain_id
            broker_dir.mkdir(parents=True, exist_ok=False)
            bundle_path = broker_dir / "02-prepare-sec-evidence.json"
            _atomic_bytes(bundle_path, parent_bytes)
            copied = bounded_regular_file(bundle_path, _MAX_PACKET)
            if hashlib.sha256(copied).hexdigest() != parent_worker.packet_sha256:
                raise HandoffError("broker SEC bundle differs from parent packet")
            remaining = deadline - time.monotonic()
            if remaining <= 1:
                return self._terminal(chain_id, phase, "timed_out", started)
            completed_at = datetime.now(timezone.utc)
            handoff = create_handoff(
                policy, parent_result, bundle_path, source, chain_id,
                completed_at, completed_at + timedelta(seconds=remaining),
            )
            handoff_path = broker_dir / "handoff.json"
            _atomic_bytes(handoff_path, handoff.raw)
            self.ledger.transition(
                chain_id, "handoff_ready", handoff_sha256=handoff.sha256,
                handoff_calls=1,
            )
            if time.monotonic() >= deadline:
                return self._terminal(chain_id, phase, "timed_out", started)
            verify_handoff(
                bounded_regular_file(handoff_path, 16 * 1024),
                handoff.sha256, policy, datetime.now(timezone.utc),
            )
            phase = "child"
            self.ledger.transition(chain_id, "child_running", child_id=child_id)
            child_spec = self._spec(
                agent_id=CHILD_ID, chain_id=chain_id,
                request_id=request_id, run_id=child_id,
                params={
                    "handoff_path": str(handoff_path),
                    "handoff_sha256": handoff.sha256,
                    "bundle_path": str(bundle_path),
                    "approved_run_root": str(self.approved_run_root),
                }, policy_sha256=policy.sha256,
                broker_dir=broker_dir, handoff_sha256=handoff.sha256,
            )
            child_worker = self.worker(child_spec, deadline, self.cancel_event)
            if child_worker.status != "completed":
                return self._terminal(chain_id, phase, child_worker.status, started)
            child_packet, _ = self._checked_packet(
                child_worker, child_id, "03-write-sec-review.json", _REPORT,
                "builtin.markdown-sec-independent-review",
            )
            self._checked_state(child_id, CHILD_ID, child_packet, chain_id)
            report = child_packet.records[0]
            report_path = Path(report["path"])
            if (
                Path(os.path.abspath(report_path)).parent != self.run_root / child_id
                or report_path.name != "sec_independent_review.md"
                or report["format"] != "markdown"
            ):
                raise HandoffError("child report path differs from fixed run")
            report_raw = bounded_regular_file(report_path, _MAX_REPORT)
            if hashlib.sha256(report_raw).hexdigest() != report["artifact_sha256"]:
                raise HandoffError("child review report hash differs")
            self.ledger.transition(
                chain_id, "completed", wall_ms=self._elapsed_ms(started),
                model_cost_minor=0,
            )
            return ChainResult.from_ledger(self.ledger.get(chain_id))
        except Exception as exc:
            # Persist a non-sensitive code; source content and local paths never enter audit.
            code = "handoff_invalid" if isinstance(exc, HandoffError) else "internal_error"
            self.ledger.transition(
                chain_id, "failed", failure_code=code,
                wall_ms=self._elapsed_ms(started),
            )
            return ChainResult.from_ledger(self.ledger.get(chain_id))
