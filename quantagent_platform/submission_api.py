"""Explicitly enabled, single-owner admission for pre-registered offline thesis inputs."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, ValidationError

from .agents import AgentError, AgentRuntime
from .contracts import ContractError, sha256_json
from .research_contracts import validate_review_fixture
from .result_api import ApiConfig, ArtifactIntegrityError, ReadApiError, ResultStore, RunSummary, _read_bounded
from .runner import RecipeError


SUBMIT_CONTRACT = "quantagent.submit_run.v1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{15,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_BODY_BYTES = 4096
_MAX_FIXTURE_BYTES = 2 * 1024 * 1024
_SELECTION = {
    "agent_id": "builtin.research-agent",
    "agent_version": "1.0.0",
    "skill_id": "anthropic-financial-services-adapted.thesis-tracker",
    "skill_version": "1.0.0",
    "recipe_id": "thesis-tracker",
    "recipe_version": "1.0.0",
}
_BINDINGS = {"source.thesis_review": "builtin.json-thesis-review-source"}
_PERMISSIONS = {"filesystem:read", "filesystem:write"}


class InvalidSubmission(ReadApiError):
    status_code = 422
    code = "invalid_submission"
    public_message = "The submission is invalid or not allow-listed."


class SubmissionTooLarge(ReadApiError):
    status_code = 413
    code = "submission_too_large"
    public_message = "The submission exceeds the request size limit."


class IdempotencyConflict(ReadApiError):
    status_code = 409
    code = "idempotency_conflict"
    public_message = "The idempotency key is already bound to another submission."


class SubmissionPending(ReadApiError):
    status_code = 409
    code = "submission_pending"
    public_message = "The submission is being recorded; retry with the same key."


class FixtureChanged(ReadApiError):
    status_code = 409
    code = "fixture_changed"
    public_message = "The registered input has changed since server startup."


class ExecutionFailed(ReadApiError):
    status_code = 500
    code = "execution_failed"
    public_message = "The admitted run failed; its run summary may contain status details."


class SubmitRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_type: Literal["quantagent.submit_run.v1"]
    fixture_id: str
    fixture_sha256: str
    request_id: str


@dataclass(frozen=True)
class RegisteredFixture:
    path: Path
    sha256: str


@dataclass(frozen=True)
class SubmissionConfig:
    """The operator, not an HTTP client, chooses the readable fixture files."""

    fixtures: dict[str, str | Path]
    registered: dict[str, RegisteredFixture] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.fixtures:
            raise ValueError("at least one registered fixture is required")
        registered: dict[str, RegisteredFixture] = {}
        for fixture_id, value in self.fixtures.items():
            if not isinstance(fixture_id, str) or not _ID.fullmatch(fixture_id):
                raise ValueError("fixture ids must use 1-64 safe characters")
            path = Path(value).expanduser()
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"registered fixture is not a regular file: {fixture_id}")
            path = path.resolve(strict=True)
            try:
                content = _read_bounded(path, _MAX_FIXTURE_BYTES)
                fixture = _decode_fixture(content)
                validate_review_fixture(fixture)
            except (ArtifactIntegrityError, ContractError, ValueError) as exc:
                raise ValueError(f"registered fixture failed validation: {fixture_id}") from exc
            registered[fixture_id] = RegisteredFixture(
                path=path,
                sha256=hashlib.sha256(content).hexdigest(),
            )
        object.__setattr__(self, "registered", registered)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(_: str) -> None:
    raise ValueError("non-JSON number")


def _decode_fixture(content: bytes) -> dict[str, Any]:
    value = json.loads(
        content.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("fixture must be a JSON object")
    return value


async def _request_value(request: Request) -> SubmitRunRequest:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise InvalidSubmission()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_BODY_BYTES:
            raise SubmissionTooLarge()
        chunks.append(chunk)
    try:
        value = _decode_fixture(b"".join(chunks))
        parsed = SubmitRunRequest.model_validate(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise InvalidSubmission() from exc
    if (
        not _ID.fullmatch(parsed.fixture_id)
        or not _ID.fullmatch(parsed.request_id)
        or not _SHA256.fullmatch(parsed.fixture_sha256)
    ):
        raise InvalidSubmission()
    return parsed


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

    def execute(source: RegisteredFixture, **kwargs: Any) -> None:
        with run_lock:
            try:
                content = _read_bounded(source.path, _MAX_FIXTURE_BYTES)
            except ArtifactIntegrityError as exc:
                raise FixtureChanged() from exc
            if hashlib.sha256(content).hexdigest() != source.sha256:
                raise FixtureChanged()
            runtime.run(**kwargs)

    def existing(run_id: str, request_sha256: str) -> tuple[int, Any]:
        run_dir = store.root / run_id
        state_path = run_dir / "run.json"
        if run_dir.is_symlink() or state_path.is_symlink():
            raise ArtifactIntegrityError()
        if not state_path.exists():
            raise SubmissionPending()
        _, state = store._load_state(run_id, api_config.owner_subject)
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
        if (store.root / run_id).exists() or (store.root / run_id).is_symlink():
            status, summary = existing(run_id, request_sha256)
        else:
            try:
                content = _read_bounded(fixture.path, _MAX_FIXTURE_BYTES)
                if hashlib.sha256(content).hexdigest() != fixture.sha256:
                    raise FixtureChanged()
                validated = validate_review_fixture(_decode_fixture(content))
                if validated["research_request"]["request_id"] != body.request_id:
                    raise InvalidSubmission()
            except (ArtifactIntegrityError, ContractError, ValueError) as exc:
                raise FixtureChanged() from exc
            try:
                await run_in_threadpool(
                    execute,
                    fixture,
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
            except FileExistsError:
                status, summary = existing(run_id, request_sha256)
            except (AgentError, RecipeError) as exc:
                raise ExecutionFailed() from exc
            else:
                status = 201
                summary = store.summary(run_id, requester_subject=subject)
        response.status_code = status
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Location"] = f"/api/v1/runs/{run_id}"
        return summary
