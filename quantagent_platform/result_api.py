"""Read routes and original owner aliases; application assembly uses the startup port."""
from __future__ import annotations
import hmac
from typing import TYPE_CHECKING, Annotated, Callable
from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .contracts import sha256_json
from .api_contracts import (
    RUN_SUMMARY_CONTRACT, REPORT_CONTRACT, ExactRef, AgentSelection, RecipeRef, FinalResultRef,
    StepSummary, ResultLinks, RunSummary, ReportArtifact, ApiConfig, ReadApiError,
    AuthenticationRequired, AccessDenied, RunNotFound, ResultUnavailable, ArtifactIntegrityError,
)
from .api_storage import ResultStore, read_bounded as _read_bounded
from .api_ports import get_api_app_factory
if TYPE_CHECKING:
    from .api_requests import SubmissionConfig


def install_result_routes(
    app: FastAPI, config: ApiConfig, store: ResultStore, *, submission_enabled: bool = False,
) -> Callable[..., str]:
    security = HTTPBearer(auto_error=False)

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
            "mode": "controlled_local_submit" if submission_enabled else "read_only",
            "api_version": "v2" if submission_enabled else "v1",
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

    return authenticate


def create_app(config: ApiConfig, submission: SubmissionConfig | None = None) -> FastAPI:
    """Original entry; default assembly is injected by the designated package startup."""
    return get_api_app_factory()(config, submission)
