"""Системные роуты: health, ready, meta (docs/09-api.md §3, §4.1)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Response

from alfa_insight import __version__
from alfa_insight.api.deps import get_ctx
from alfa_insight.api.schemas import HealthResponse, MetaResponse, ReadyResponse, RoleInfoOut
from alfa_insight.appctx import AppContext

router = APIRouter(tags=["system"])


def role_infos(ctx: AppContext) -> list[RoleInfoOut]:
    return [RoleInfoOut(id=rid, name=r.name, short=r.short) for rid, r in ctx.demo.roles.items()]  # type: ignore[arg-type]


def budget_mode(ctx: AppContext) -> str:
    budget = ctx.router.budget
    return budget.mode() if budget is not None else "normal"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


def readiness(ctx: AppContext) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    try:
        checks["sqlite"] = ctx.db.scalar("SELECT 1") == 1
    except Exception:
        checks["sqlite"] = False
    try:
        from importlib import resources

        files = [
            f
            for f in resources.files("alfa_insight.db").joinpath("migrations").iterdir()
            if f.name.endswith(".sql")
        ]
        checks["migrations"] = int(ctx.db.scalar("SELECT count(*) FROM schema_migrations") or 0) >= len(files)
    except Exception:
        checks["migrations"] = False
    try:
        checks["duckdb"] = ctx.settings.duckdb_path.exists() and ctx.duck.scalar("SELECT 1") == 1
    except Exception:
        checks["duckdb"] = False
    try:
        checks["profiles"] = checks["duckdb"] and bool(ctx.profiles.company_ids())
    except Exception:
        checks["profiles"] = False
    checks["taxonomy"] = bool(ctx.taxonomy.industries)
    return checks


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(response: Response, ctx: AppContext = Depends(get_ctx)) -> ReadyResponse:
    checks = await asyncio.to_thread(readiness, ctx)
    ok = all(checks.values())
    if not ok:
        response.status_code = 503
    return ReadyResponse(ready=ok, checks=checks)


@router.get("/meta", response_model=MetaResponse)
async def meta(ctx: AppContext = Depends(get_ctx)) -> MetaResponse:
    s = ctx.settings
    return MetaResponse(
        version=__version__, demo_mode=s.demo_mode, llm_mode=s.llm_mode, data_profile=s.data_profile,
        budget_mode=budget_mode(ctx), roles=role_infos(ctx),  # type: ignore[arg-type]
    )  # fmt: skip
