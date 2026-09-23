from __future__ import annotations

import hashlib
import hmac
import json
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from .contracts import ContractError, DataPacket, parse_aware_timestamp, sha256_json

if TYPE_CHECKING:
    from .submission_api import SubmissionConfig


RUN_SUMMARY_CONTRACT = "quantagent.read_api.run_summary.v1"
REPORT_CONTRACT = "quantagent.report.v1"

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_MAX_STATE_BYTES = 2 * 1024 * 1024
_MAX_PACKET_BYTES = 16 * 1024 * 1024
_MAX_REPORT_BYTES = 4 * 1024 * 1024


class ExactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str


class AgentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["agent"]
    agent: ExactRef
    skill: ExactRef
    recipe: ExactRef


class RecipeRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str


class FinalResultRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str
    content_sha256: str


class StepSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    plugin_id: str
    plugin_version: str
    capability: str
    output_contract: str
    output_sha256: str
    status: str


class ResultLinks(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report: str | None


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_type: Literal["quantagent.read_api.run_summary.v1"]
    run_id: str
    recipe: RecipeRef
    status: Literal["running", "failed", "completed"]
    started_at: str
    completed_at: str | None
    offline: bool
    selection: AgentSelection | None
    steps: list[StepSummary]
    final: FinalResultRef | None
    failure_type: str | None
    links: ResultLinks


@dataclass(frozen=True)
class ReportArtifact:
    content: bytes
    sha256: str


class ReadApiError(RuntimeError):
    status_code = 500
    code = "read_api_error"
    public_message = "The result could not be read."
    headers: dict[str, str] = {}


class AuthenticationRequired(ReadApiError):
    status_code = 401
    code = "authentication_required"
    public_message = "Valid bearer authentication is required."
    headers = {"WWW-Authenticate": "Bearer"}


class AccessDenied(ReadApiError):
    status_code = 403
    code = "access_denied"
    public_message = "The authenticated subject cannot read this run collection."


class RunNotFound(ReadApiError):
    status_code = 404
    code = "run_not_found"
    public_message = "The requested run was not found."


class ResultUnavailable(ReadApiError):
    status_code = 409
    code = "result_unavailable"
    public_message = "The run does not have a completed Markdown result."


class ArtifactIntegrityError(ReadApiError):
    status_code = 409
    code = "artifact_integrity_error"
    public_message = "The stored run artifacts failed integrity validation."


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-JSON number is forbidden: {value}")


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        if path.is_symlink() or not path.is_file():
            raise ArtifactIntegrityError()
        size = path.stat().st_size
        if size > limit:
            raise ArtifactIntegrityError()
        raw = path.read_bytes()
    except ArtifactIntegrityError:
        raise
    except OSError as exc:
        raise ArtifactIntegrityError() from exc
    if len(raw) > limit:
        raise ArtifactIntegrityError()
    return raw


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    try:
        value = json.loads(
            _read_bounded(path, limit).decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ArtifactIntegrityError() from exc
    if not isinstance(value, dict):
        raise ArtifactIntegrityError()
    return value


def _string(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactIntegrityError()
    return value


def _sha256(value: Any) -> str:
    text = _string(value)
    if not _SHA256.fullmatch(text):
        raise ArtifactIntegrityError()
    return text


def _timestamp(value: Any) -> str:
    text = _string(value)
    try:
        parse_aware_timestamp(text, "timestamp")
    except ContractError as exc:
        raise ArtifactIntegrityError() from exc
    return text


def _artifact_name(value: Any, suffix: str) -> str:
    raw = _string(value)
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name in {".", ".."} or not name.endswith(suffix):
        raise ArtifactIntegrityError()
    return name


class ResultStore:
    """Read one subject's immutable run artifacts without trusting stored paths."""

    def __init__(self, run_root: str | Path, *, owner_subject: str):
        root = Path(run_root).expanduser().resolve()
        if not root.is_dir() or root.is_symlink():
            raise ValueError("run_root must be an existing non-symlink directory")
        if not isinstance(owner_subject, str) or not owner_subject.strip():
            raise ValueError("owner_subject must be a non-empty string")
        self.root = root
        self.owner_subject = owner_subject

    def _authorize(self, requester_subject: str) -> None:
        if requester_subject != self.owner_subject:
            raise AccessDenied()

    def _run_dir(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise RunNotFound()
        candidate = self.root / run_id
        try:
            if candidate.is_symlink():
                raise RunNotFound()
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise RunNotFound() from exc
        if resolved.parent != self.root or not resolved.is_dir():
            raise RunNotFound()
        return resolved

    def _load_state(self, run_id: str, requester_subject: str) -> tuple[Path, dict[str, Any]]:
        self._authorize(requester_subject)
        run_dir = self._run_dir(run_id)
        state_path = run_dir / "run.json"
        if state_path.resolve(strict=False).parent != run_dir:
            raise ArtifactIntegrityError()
        state = _read_json(state_path, _MAX_STATE_BYTES)
        if state.get("run_id") != run_id:
            raise ArtifactIntegrityError()
        return run_dir, state

    @staticmethod
    def _selection(invocation: Any) -> AgentSelection | None:
        if invocation is None:
            return None
        if not isinstance(invocation, dict) or invocation.get("type") != "agent":
            raise ArtifactIntegrityError()

        def ref(name: str) -> ExactRef:
            value = invocation.get(name)
            if not isinstance(value, dict):
                raise ArtifactIntegrityError()
            return ExactRef(id=_string(value.get("id")), version=_string(value.get("version")))

        return AgentSelection(
            type="agent",
            agent=ref("agent"),
            skill=ref("skill"),
            recipe=ref("recipe"),
        )

    @staticmethod
    def _steps(value: Any) -> list[StepSummary]:
        if not isinstance(value, list):
            raise ArtifactIntegrityError()
        rows: list[StepSummary] = []
        for item in value:
            if not isinstance(item, dict):
                raise ArtifactIntegrityError()
            rows.append(
                StepSummary(
                    id=_string(item.get("id")),
                    plugin_id=_string(item.get("plugin_id")),
                    plugin_version=_string(item.get("plugin_version")),
                    capability=_string(item.get("capability")),
                    output_contract=_string(item.get("output_contract")),
                    output_sha256=_sha256(item.get("output_sha256")),
                    status=_string(item.get("status")),
                )
            )
        return rows

    def _summary_from_state(self, run_id: str, state: dict[str, Any]) -> RunSummary:
        status = state.get("status")
        if status not in {"running", "failed", "completed"}:
            raise ArtifactIntegrityError()
        started_at = _timestamp(state.get("started_at"))
        completed_at = state.get("completed_at")
        if completed_at is not None:
            completed_at = _timestamp(completed_at)
        if status in {"failed", "completed"} and completed_at is None:
            raise ArtifactIntegrityError()
        offline = state.get("offline")
        if not isinstance(offline, bool):
            raise ArtifactIntegrityError()
        recipe = RecipeRef(
            id=_string(state.get("recipe_id")),
            version=_string(state.get("recipe_version")),
        )
        steps = self._steps(state.get("steps"))
        final: FinalResultRef | None = None
        if status == "completed":
            final = FinalResultRef(
                contract=_string(state.get("final_contract")),
                content_sha256=_sha256(state.get("final_sha256")),
            )
        failure_type: str | None = None
        if status == "failed":
            error = state.get("error")
            if not isinstance(error, dict):
                raise ArtifactIntegrityError()
            failure_type = _string(error.get("type"))
        report_link = None
        if final is not None and final.contract == REPORT_CONTRACT:
            report_link = f"/api/v1/runs/{run_id}/report"
        return RunSummary(
            contract_type=RUN_SUMMARY_CONTRACT,
            run_id=run_id,
            recipe=recipe,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            offline=offline,
            selection=self._selection(state.get("invocation")),
            steps=steps,
            final=final,
            failure_type=failure_type,
            links=ResultLinks(report=report_link),
        )

    def summary(self, run_id: str, *, requester_subject: str) -> RunSummary:
        _, state = self._load_state(run_id, requester_subject)
        return self._summary_from_state(run_id, state)

    def report(self, run_id: str, *, requester_subject: str) -> ReportArtifact:
        run_dir, state = self._load_state(run_id, requester_subject)
        summary = self._summary_from_state(run_id, state)
        if (
            summary.status != "completed"
            or summary.final is None
            or summary.final.contract != REPORT_CONTRACT
            or not state["steps"]
        ):
            raise ResultUnavailable()
        final_step = state["steps"][-1]
        if not isinstance(final_step, dict):
            raise ArtifactIntegrityError()
        if (
            final_step.get("status") != "completed"
            or final_step.get("output_contract") != REPORT_CONTRACT
            or final_step.get("output_sha256") != summary.final.content_sha256
        ):
            raise ArtifactIntegrityError()
        packet_name = _artifact_name(final_step.get("packet_path"), ".json")
        packet_path = run_dir / packet_name
        if packet_path.resolve(strict=False).parent != run_dir:
            raise ArtifactIntegrityError()
        try:
            packet = DataPacket.from_dict(_read_json(packet_path, _MAX_PACKET_BYTES))
        except (ContractError, TypeError, ValueError) as exc:
            raise ArtifactIntegrityError() from exc
        if (
            packet.contract_version != REPORT_CONTRACT
            or packet.content_sha256 != summary.final.content_sha256
            or len(packet.records) != 1
        ):
            raise ArtifactIntegrityError()
        record = packet.records[0]
        if record.get("format") != "markdown":
            raise ArtifactIntegrityError()
        report_name = _artifact_name(record.get("path"), ".md")
        report_path = run_dir / report_name
        if report_path.resolve(strict=False).parent != run_dir:
            raise ArtifactIntegrityError()
        content = _read_bounded(report_path, _MAX_REPORT_BYTES)
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ArtifactIntegrityError() from exc
        expected_sha256 = _sha256(record.get("artifact_sha256"))
        if hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ArtifactIntegrityError()
        return ReportArtifact(content=content, sha256=expected_sha256)


@dataclass(frozen=True)
class ApiConfig:
    run_root: Path
    owner_subject: str
    bearer_token: str

    def __post_init__(self) -> None:
        if not isinstance(self.bearer_token, str) or len(self.bearer_token) < 32:
            raise ValueError("bearer_token must contain at least 32 characters")
        if not self.bearer_token.strip():
            raise ValueError("bearer_token cannot be whitespace")


def create_app(config: ApiConfig, submission: SubmissionConfig | None = None) -> FastAPI:
    store = ResultStore(config.run_root, owner_subject=config.owner_subject)
    security = HTTPBearer(auto_error=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            worker = getattr(app.state, "local_task_worker", None)
            if worker is not None:
                worker.shutdown()

    app = FastAPI(
        title="QuantAgent Read API",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    def authenticate(
        credentials: HTTPAuthorizationCredentials | None = Depends(security),
    ) -> str:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, config.bearer_token)
        ):
            raise AuthenticationRequired()
        return config.owner_subject

    @app.exception_handler(ReadApiError)
    async def handle_read_error(_: Request, exc: ReadApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.public_message}},
            headers={**exc.headers, "Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "mode": "controlled_local_submit" if submission is not None else "read_only",
            "api_version": "v2" if submission is not None else "v1",
        }

    @app.get("/api/v1/runs/{run_id}", response_model=RunSummary)
    def get_run(
        run_id: str,
        response: Response,
        subject: str = Depends(authenticate),
    ) -> RunSummary:
        summary = store.summary(run_id, requester_subject=subject)
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["ETag"] = f'"{sha256_json(summary.model_dump(mode="json"))}"'
        return summary

    @app.get("/api/v1/runs/{run_id}/report")
    def get_report(
        run_id: str,
        subject: str = Depends(authenticate),
        if_none_match: Annotated[str | None, Header()] = None,
    ) -> Response:
        artifact = store.report(run_id, requester_subject=subject)
        etag = f'"{artifact.sha256}"'
        headers = {
            "Cache-Control": "private, no-store",
            "ETag": etag,
            "Content-Disposition": 'inline; filename="quantagent-report.md"',
            "X-Content-Type-Options": "nosniff",
        }
        if if_none_match == etag:
            return Response(status_code=304, headers=headers)
        return Response(
            content=artifact.content,
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )

    if submission is not None:
        from .submission_api import install_submission_route
        from .task_lifecycle_api import install_task_lifecycle_routes

        install_submission_route(app, config, store, authenticate, submission)
        install_task_lifecycle_routes(app, config, store, authenticate, submission)

    return app
