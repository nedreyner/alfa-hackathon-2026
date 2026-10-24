"""FastAPI-приложение: lifespan, ошибки, роуты (docs/09-api.md, docs/02-architecture.md §7)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute

from alfa_insight import __version__
from alfa_insight.api import errors
from alfa_insight.api.ratelimit import RateLimiter
from alfa_insight.api.routes import (
    companies,
    feed,
    insights,
    profile,
    reference,
    runs,
    session,
    sources,
    system,
    telemetry,
)
from alfa_insight.appctx import AppContext, build_context
from alfa_insight.log import get_logger
from alfa_insight.services.jobs import JobRunner

log = get_logger("api.app")
ROUTERS = [
    system.router, companies.router, session.router, reference.router, profile.router, feed.router,
    insights.router, sources.router, telemetry.router, runs.router,
]  # fmt: skip


def _operation_id(route: APIRoute) -> str:
    return route.name


def create_app(ctx: AppContext | None = None, *, run_worker: bool | None = None) -> FastAPI:
    """`ctx` — готовый контекст (тесты); иначе собирается из настроек при старте."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app_ctx = ctx or build_context()
        app.state.ctx = app_ctx
        app.state.runner = JobRunner(app_ctx)
        app.state.limiter = RateLimiter()
        app.state.runner.recover_stale()
        scheduler: Any = None
        embedded = app_ctx.settings.run_worker_in_api if run_worker is None else run_worker
        if embedded:
            from alfa_insight.worker.main import start_embedded

            scheduler, _jobs, _task = start_embedded(app_ctx)
        log.info(
            "api_started",
            demo_mode=app_ctx.settings.demo_mode,
            llm_mode=app_ctx.settings.llm_mode,
            worker=embedded,
        )
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await asyncio.wait_for(app.state.runner.wait_all(), timeout=5)

    app = FastAPI(
        title="Альфа Инсайт API", version=__version__, lifespan=lifespan,
        generate_unique_id_function=_operation_id, docs_url="/api/docs", openapi_url="/api/openapi.json",
    )  # fmt: skip
    errors.install(app)
    for r in ROUTERS:
        app.include_router(r, prefix="/api")
    return app
