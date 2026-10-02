"""Explicitly enabled, single-owner admission for pre-registered offline thesis inputs."""

from __future__ import annotations

import hashlib
from threading import Lock
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.concurrency import run_in_threadpool

from .agents import AgentError, AgentRuntime
from .contracts import ContractError, sha256_json
from .research_contracts import validate_review_fixture
from .api_contracts import (
    ApiConfig, ArtifactIntegrityError, ReadApiError, RunSummary, SUBMIT_CONTRACT,
    InvalidSubmission, SubmissionTooLarge, IdempotencyConflict, SubmissionPending,
    FixtureChanged, ExecutionFailed, SubmitRunRequest, RegisteredFixture,
)
from .api_storage import ResultStore, read_bounded as _read_bounded
from .api_requests import (
    SubmissionConfig, decode_fixture as _decode_fixture, parse_submission_request as _request_value,
    KEY_PATTERN as _KEY, MAX_FIXTURE_BYTES as _MAX_FIXTURE_BYTES,
    RESEARCH_SELECTION as _SELECTION, RESEARCH_BINDINGS as _BINDINGS, RESEARCH_PERMISSIONS as _PERMISSIONS,
)
from .runner import RecipeError


def _run_id(subject: str, key: str) -> str:
    digest = hashlib.sha256(f"{subject}\0{key}".encode("utf-8")).hexdigest()
    return f"api-{digest[:32]}"


def install_submission_route(
    app: FastAPI,
    api_config: ApiConfig,
    store: ResultStore,
    authenticate: Callable[..., str],
    config: SubmissionConfig,
) -> None:
    for fixture in config.registered.values():
        if fixture.path.is_relative_to(store.root):
            raise ValueError("registered fixtures must be outside the run root")
    runtime = AgentRuntime()
    runtime.resolve(
        **_SELECTION,
        bindings=_BINDINGS,
        allowed_permissions=_PERMISSIONS,
        offline=True,
    )
    run_lock = Lock()

    def execute(
        source: RegisteredFixture, request_sha256: str, request_id: str, **kwargs: Any
    ) -> tuple[int, RunSummary]:
        run_id = kwargs["run_id"]
        with run_lock:
            if (store.root / run_id).exists() or (store.root / run_id).is_symlink():
                return existing(run_id, request_sha256)
            try:
                content = _read_bounded(source.path, _MAX_FIXTURE_BYTES)
                if hashlib.sha256(content).hexdigest() != source.sha256:
                    raise FixtureChanged()
                validated = validate_review_fixture(_decode_fixture(content))
                if validated["research_request"]["request_id"] != request_id:
                    raise InvalidSubmission()
            except ArtifactIntegrityError as exc:
                raise FixtureChanged() from exc
            except (ContractError, ValueError) as exc:
                raise FixtureChanged() from exc
            try:
                runtime.run(**kwargs)
            except FileExistsError:
                return existing(run_id, request_sha256)
            return 201, store.summary(run_id, requester_subject=api_config.owner_subject)

    def existing(run_id: str, request_sha256: str) -> tuple[int, RunSummary]:
        run_dir = store.root / run_id
        state_path = run_dir / "run.json"
        if run_dir.is_symlink() or state_path.is_symlink():
            raise ArtifactIntegrityError()
        if not state_path.exists():
            raise SubmissionPending()
        _, state = store.load_state(run_id, api_config.owner_subject)
        invocation = state.get("invocation")
        submission = invocation.get("submission") if isinstance(invocation, dict) else None
        if not isinstance(submission, dict) or submission.get("request_sha256") != request_sha256:
            raise IdempotencyConflict()
        return 200, store.summary(run_id, requester_subject=api_config.owner_subject)

    @app.post("/api/v1/runs", response_model=RunSummary)
    async def submit_run(
        request: Request,
        response: Response,
        subject: str = Depends(authenticate),
        idempotency_key: str | None = Header(default=None),
    ) -> RunSummary:
        if idempotency_key is None or not _KEY.fullmatch(idempotency_key):
            raise InvalidSubmission()
        body = await _request_value(request)
        fixture = config.registered.get(body.fixture_id)
        if fixture is None or fixture.sha256 != body.fixture_sha256:
            raise InvalidSubmission()
        request_sha256 = sha256_json(body.model_dump(mode="json"))
        run_id = _run_id(subject, idempotency_key)
        completed = None
        if (store.root / run_id).exists() or (store.root / run_id).is_symlink():
            try:
                completed = existing(run_id, request_sha256)
            except SubmissionPending:
                pass
        if completed is not None and completed[1].status != "running":
            status, summary = completed
        else:
            try:
                status, summary = await run_in_threadpool(
                    execute,
                    fixture,
                    request_sha256,
                    body.request_id,
                    **_SELECTION,
                    params={"source_path": str(fixture.path), "report_title": "QuantAgent thesis review"},
                    output_dir=store.root,
                    allowed_read_roots=[fixture.path.parent],
                    bindings=_BINDINGS,
                    allowed_permissions=_PERMISSIONS,
                    offline=True,
                    run_id=run_id,
                    submission_context={
                        "contract_type": SUBMIT_CONTRACT,
                        "request_sha256": request_sha256,
                        "fixture_id": body.fixture_id,
                        "fixture_sha256": fixture.sha256,
                    },
                )
            except (AgentError, RecipeError) as exc:
                raise ExecutionFailed() from exc
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Location"] = f"/api/v1/runs/{run_id}"
        return summary
