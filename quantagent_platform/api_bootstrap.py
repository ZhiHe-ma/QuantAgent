"""Designated HTTP application assembly; package import binds without loading HTTP SDKs."""
from __future__ import annotations
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any
from .api_ports import configure_api_app_factory
if TYPE_CHECKING:
    from .api_contracts import ApiConfig
    from .api_requests import SubmissionConfig


def build_api_app(config: ApiConfig, submission: SubmissionConfig | None = None) -> Any:
    """Build one original local API; load optional HTTP dependencies only here."""
    from fastapi import FastAPI
    from .api_storage import ResultStore
    from .result_api import install_result_routes

    store = ResultStore(config.run_root, owner_subject=config.owner_subject)

    @asynccontextmanager
    async def lifespan(app: Any):
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
    authenticate = install_result_routes(app, config, store, submission_enabled=submission is not None)
    if submission is not None:
        from .submission_api import install_submission_route
        from .task_lifecycle_api import install_task_lifecycle_routes
        install_submission_route(app, config, store, authenticate, submission)
        install_task_lifecycle_routes(app, config, store, authenticate, submission)
    return app


def install_api_app_factory() -> None:
    """Bind assembly only; no HTTP imports, app, worker, directories or database."""
    configure_api_app_factory(build_api_app)
