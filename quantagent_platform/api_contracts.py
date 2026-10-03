"""Stable shared HTTP models, errors and value configuration; no runtime IO."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict

RUN_SUMMARY_CONTRACT = "quantagent.read_api.run_summary.v1"
REPORT_CONTRACT = "quantagent.report.v1"
SUBMIT_CONTRACT = "quantagent.submit_run.v1"


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
