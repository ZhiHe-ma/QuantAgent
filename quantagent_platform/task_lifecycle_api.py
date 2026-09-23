"""Single-process, local-only task admission with persisted status and cooperative cancel."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .agents import AgentRuntime
from .contracts import ContractError, parse_aware_timestamp, sha256_json, utc_now
from .research_contracts import validate_review_fixture
from .result_api import ApiConfig, ArtifactIntegrityError, ReadApiError, ResultStore, _read_bounded
from .runner import RunCancelled
from .submission_api import (
    _BINDINGS,
    _KEY,
    _MAX_FIXTURE_BYTES,
    _PERMISSIONS,
    _SELECTION,
    _decode_fixture,
    _request_value,
    FixtureChanged,
    IdempotencyConflict,
    InvalidSubmission,
    RegisteredFixture,
    SubmissionConfig,
    SubmissionPending,
)


TASK_CONTRACT = "quantagent.run_status.v2"
_TASK_ID = re.compile(r"^task-[a-f0-9]{32}$")
_MAX_TASK_BYTES = 16 * 1024
_MAX_INFLIGHT = 8


class TaskNotFound(ReadApiError):
    status_code = 404
    code = "task_not_found"
    public_message = "The requested task was not found."


class TaskCapacity(ReadApiError):
    status_code = 429
    code = "task_capacity_reached"
    public_message = "The local task worker is at capacity; retry later."


class TaskNotCancelable(ReadApiError):
    status_code = 409
    code = "task_not_cancelable"
    public_message = "The task has already reached a terminal state."


class TaskInterrupted(ReadApiError):
    status_code = 409
    code = "task_interrupted"
    public_message = "The task is no longer managed by this process."


class TaskLinksV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None
    report: str | None


class TaskStatusV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_type: Literal["quantagent.run_status.v2"]
    run_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    cancel_requested: bool
    created_at: str
    started_at: str | None
    completed_at: str | None
    failure_type: str | None
    links: TaskLinksV2


class _TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_type: Literal["quantagent.run_status.v2"]
    run_id: str = Field(pattern=r"^task-[a-f0-9]{32}$")
    owner_subject: str = Field(min_length=1)
    process_nonce: str = Field(pattern=r"^[a-f0-9]{32}$")
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    fixture_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    fixture_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    cancel_requested: bool
    created_at: str
    started_at: str | None
    completed_at: str | None
    failure_type: str | None


def _task_id(subject: str, key: str) -> str:
    digest = hashlib.sha256(f"v2\0{subject}\0{key}".encode("utf-8")).hexdigest()
    return f"task-{digest[:32]}"


class LocalTaskWorker:
    """One worker per app; records survive restart but unfinished jobs do not resume."""

    def __init__(self, api_config: ApiConfig, store: ResultStore) -> None:
        self.api_config = api_config
        self.store = store
        self.root = store.root / ".tasks-v2"
        if self.root.is_symlink() or (self.root.exists() and not self.root.is_dir()):
            raise ValueError("task record root must be a non-symlink directory")
        self.nonce = uuid.uuid4().hex
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="quantagent-task")
        self.events: dict[str, Event] = {}
        self.inflight = 0
        self.runtime = AgentRuntime()
        self.runtime.resolve(
            **_SELECTION,
            bindings=_BINDINGS,
            allowed_permissions=_PERMISSIONS,
            offline=True,
        )

    def shutdown(self) -> None:
        with self.lock:
            for event in self.events.values():
                event.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _directory(self, run_id: str) -> Path:
        if not _TASK_ID.fullmatch(run_id):
            raise TaskNotFound()
        if self.root.is_symlink():
            raise ArtifactIntegrityError()
        return self.root / run_id

    def _load(self, run_id: str) -> dict[str, Any]:
        directory = self._directory(run_id)
        if not directory.exists() or directory.is_symlink():
            raise TaskNotFound()
        if not directory.is_dir():
            raise ArtifactIntegrityError()
        path = directory / "task.json"
        if not path.exists():
            raise SubmissionPending()
        try:
            raw = _decode_fixture(_read_bounded(path, _MAX_TASK_BYTES))
            task = _TaskRecord.model_validate(raw).model_dump(mode="json")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise ArtifactIntegrityError() from exc
        if (
            task["run_id"] != run_id
            or task.get("owner_subject") != self.api_config.owner_subject
            or (task["status"] == "queued" and task["started_at"] is not None)
            or (task["status"] == "running" and task["started_at"] is None)
            or (task["status"] == "completed" and task["started_at"] is None)
            or (task["status"] in {"queued", "running"} and task["completed_at"] is not None)
            or (task["status"] in {"queued", "running"} and task["failure_type"] is not None)
            or (task["status"] in {"completed", "failed", "cancelled"} and task["completed_at"] is None)
            or (task["status"] == "completed" and task["failure_type"] is not None)
            or (task["status"] in {"failed", "cancelled"} and not task["failure_type"])
            or (task["status"] == "cancelled" and not task["cancel_requested"])
        ):
            raise ArtifactIntegrityError()
        try:
            for name in ("created_at", "started_at", "completed_at"):
                if task[name] is not None:
                    parse_aware_timestamp(task[name], name)
        except ContractError as exc:
            raise ArtifactIntegrityError() from exc
        return task

    def _save(self, task: dict[str, Any]) -> None:
        path = self._directory(task["run_id"]) / "task.json"
        if path.is_symlink():
            raise ArtifactIntegrityError()
        temporary = path.with_name("task.json.tmp")
        if temporary.is_symlink():
            raise ArtifactIntegrityError()
        temporary.write_text(
            json.dumps(task, ensure_ascii=False, sort_keys=True, allow_nan=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def _public(self, task: dict[str, Any]) -> TaskStatusV2:
        status = task["status"]
        if status in {"queued", "running"} and (
            task["process_nonce"] != self.nonce or task["run_id"] not in self.events
        ):
            status = "interrupted"
        summary_link = None
        report_link = None
        if status == "completed":
            summary = self.store.summary(
                task["run_id"], requester_subject=self.api_config.owner_subject
            )
            if summary.status != "completed":
                raise ArtifactIntegrityError()
            summary_link = f"/api/v1/runs/{task['run_id']}"
            report_link = summary.links.report
        return TaskStatusV2(
            contract_type=TASK_CONTRACT,
            run_id=task["run_id"],
            status=status,
            cancel_requested=task["cancel_requested"],
            created_at=task["created_at"],
            started_at=task["started_at"],
            completed_at=task["completed_at"],
            failure_type="RunInterrupted" if status == "interrupted" else task["failure_type"],
            links=TaskLinksV2(summary=summary_link, report=report_link),
        )

    def status(self, run_id: str) -> TaskStatusV2:
        with self.lock:
            return self._public(self._load(run_id))

    def cancel(self, run_id: str) -> tuple[int, TaskStatusV2]:
        with self.lock:
            task = self._load(run_id)
            if task["status"] in {"queued", "running"} and task["process_nonce"] != self.nonce:
                raise TaskInterrupted()
            if task["status"] == "cancelled":
                return 200, self._public(task)
            if task["status"] in {"failed", "completed"}:
                raise TaskNotCancelable()
            event = self.events.get(run_id)
            if event is None:
                raise TaskInterrupted()
            event.set()
            task["cancel_requested"] = True
            if task["status"] == "queued":
                task["status"] = "cancelled"
                task["completed_at"] = utc_now()
                task["failure_type"] = "RunCancelled"
                code = 200
            else:
                code = 202
            self._save(task)
            return code, self._public(task)

    def admit(
        self,
        *,
        subject: str,
        key: str,
        request_sha256: str,
        fixture_id: str,
        fixture: RegisteredFixture,
        request_id: str,
    ) -> tuple[int, TaskStatusV2]:
        run_id = _task_id(subject, key)
        with self.lock:
            if self.root.is_symlink():
                raise ArtifactIntegrityError()
            directory = self._directory(run_id)
            if directory.exists() or directory.is_symlink():
                task = self._load(run_id)
                if task.get("request_sha256") != request_sha256:
                    raise IdempotencyConflict()
                return 200, self._public(task)
            if self.inflight >= _MAX_INFLIGHT:
                raise TaskCapacity()
            run_dir = self.store.root / run_id
            if run_dir.exists() or run_dir.is_symlink():
                raise IdempotencyConflict()
            try:
                content = _read_bounded(fixture.path, _MAX_FIXTURE_BYTES)
                if hashlib.sha256(content).hexdigest() != fixture.sha256:
                    raise FixtureChanged()
                validated = validate_review_fixture(_decode_fixture(content))
                if validated["research_request"]["request_id"] != request_id:
                    raise InvalidSubmission()
            except (ArtifactIntegrityError, ContractError, ValueError) as exc:
                raise FixtureChanged() from exc
            self.root.mkdir(exist_ok=True)
            if self.root.is_symlink():
                raise ArtifactIntegrityError()
            try:
                directory.mkdir(exist_ok=False)
            except FileExistsError:
                task = self._load(run_id)
                if task["request_sha256"] != request_sha256:
                    raise IdempotencyConflict()
                return 200, self._public(task)
            task = {
                "contract_type": TASK_CONTRACT,
                "run_id": run_id,
                "owner_subject": subject,
                "process_nonce": self.nonce,
                "request_sha256": request_sha256,
                "fixture_id": fixture_id,
                "fixture_sha256": fixture.sha256,
                "status": "queued",
                "cancel_requested": False,
                "created_at": utc_now(),
                "started_at": None,
                "completed_at": None,
                "failure_type": None,
            }
            self._save(task)
            event = Event()
            self.events[run_id] = event
            self.inflight += 1
            try:
                self.executor.submit(self._execute, run_id, fixture, event)
            except RuntimeError:
                self.events.pop(run_id, None)
                self.inflight -= 1
                task["status"] = "failed"
                task["completed_at"] = utc_now()
                task["failure_type"] = "WorkerUnavailable"
                self._save(task)
                raise TaskInterrupted()
            return 202, self._public(task)

    def _execute(self, run_id: str, fixture: RegisteredFixture, event: Event) -> None:
        try:
            with self.lock:
                task = self._load(run_id)
                if task["status"] == "cancelled":
                    return
                task["status"] = "running"
                task["started_at"] = utc_now()
                self._save(task)
            try:
                content = _read_bounded(fixture.path, _MAX_FIXTURE_BYTES)
                if hashlib.sha256(content).hexdigest() != fixture.sha256:
                    raise FixtureChanged()
                self.runtime.run(
                    **_SELECTION,
                    params={
                        "source_path": str(fixture.path),
                        "report_title": "QuantAgent thesis review",
                    },
                    output_dir=self.store.root,
                    allowed_read_roots=[fixture.path.parent],
                    bindings=_BINDINGS,
                    allowed_permissions=_PERMISSIONS,
                    offline=True,
                    run_id=run_id,
                    cancel_check=event.is_set,
                    submission_context={
                        "contract_type": TASK_CONTRACT,
                        "request_sha256": task["request_sha256"],
                        "fixture_id": task["fixture_id"],
                        "fixture_sha256": fixture.sha256,
                    },
                )
            except RunCancelled:
                try:
                    _, run_state = self.store._load_state(run_id, self.api_config.owner_subject)
                except ReadApiError:
                    run_state = {}
                if event.is_set() and run_state.get("status") == "cancelled":
                    status, failure_type = "cancelled", "RunCancelled"
                else:
                    status, failure_type = "failed", "RunCancelled"
            except Exception as exc:
                status, failure_type = "failed", type(exc).__name__
            else:
                status, failure_type = "completed", None
            with self.lock:
                task = self._load(run_id)
                task["status"] = status
                task["failure_type"] = failure_type
                task["completed_at"] = utc_now()
                self._save(task)
        finally:
            with self.lock:
                self.events.pop(run_id, None)
                self.inflight -= 1


def install_task_lifecycle_routes(
    app: FastAPI,
    api_config: ApiConfig,
    store: ResultStore,
    authenticate: Callable[..., str],
    config: SubmissionConfig,
) -> None:
    worker = LocalTaskWorker(api_config, store)
    app.state.local_task_worker = worker

    @app.post("/api/v2/runs", response_model=TaskStatusV2)
    async def submit_task(
        request: Request,
        response: Response,
        subject: str = Depends(authenticate),
        idempotency_key: str | None = Header(default=None),
    ) -> TaskStatusV2:
        if idempotency_key is None or not _KEY.fullmatch(idempotency_key):
            raise InvalidSubmission()
        body = await _request_value(request)
        fixture = config.registered.get(body.fixture_id)
        if fixture is None or fixture.sha256 != body.fixture_sha256:
            raise InvalidSubmission()
        code, status = worker.admit(
            subject=subject,
            key=idempotency_key,
            request_sha256=sha256_json(body.model_dump(mode="json")),
            fixture_id=body.fixture_id,
            fixture=fixture,
            request_id=body.request_id,
        )
        response.status_code = code
        response.headers["Location"] = f"/api/v2/runs/{status.run_id}"
        response.headers["Cache-Control"] = "private, no-store"
        return status

    @app.get("/api/v2/runs/{run_id}", response_model=TaskStatusV2)
    def get_task(run_id: str, response: Response, _: str = Depends(authenticate)) -> TaskStatusV2:
        status = worker.status(run_id)
        response.headers["Cache-Control"] = "private, no-store"
        return status

    @app.post("/api/v2/runs/{run_id}/cancel", response_model=TaskStatusV2)
    def cancel_task(run_id: str, response: Response, _: str = Depends(authenticate)) -> TaskStatusV2:
        code, status = worker.cancel(run_id)
        response.status_code = code
        response.headers["Cache-Control"] = "private, no-store"
        return status
