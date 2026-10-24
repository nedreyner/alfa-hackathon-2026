"""Макро, качество и админка (docs/09-api.md §3, docs/12-quality.md §6–7)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from alfa_insight.api.deps import current_session, get_ctx, get_runner, require_admin
from alfa_insight.api.schemas import MacroResponse, PrecomputeIn, ReviewIn, ReviewItem, SourceStatus
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.services.jobs import JobRunner, enqueue_precompute
from alfa_insight.services.quality import QualityResponse, quality
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.quality import QualityStore
from alfa_insight.timeutil import parse_dt
from alfa_insight.worker.jobs import WorkerJobs

router = APIRouter(tags=["macro"])
admin = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
FX = ("fx_usd", "fx_eur", "fx_cny", "fx_try", "fx_aed", "fx_inr", "fx_kzt")


@router.get("/macro", response_model=MacroResponse)
async def macro(
    s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> MacroResponse:
    store = MacroStore(ctx.db)
    key_rate = store.summary("key_rate", days=90, weekly=True)
    fx = [x for x in (store.summary(i, days=90, weekly=True) for i in FX) if x is not None]
    dates = [x.latest.date for x in [key_rate, *fx] if x is not None]
    updated = max(dates) if dates else None
    return MacroResponse(
        key_rate=key_rate, fx=fx, updated_at=parse_dt(f"{updated.isoformat()}T00:00:00Z") if updated else None
    )


@router.get("/quality", response_model=QualityResponse)
async def get_quality(
    s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> QualityResponse:
    return await asyncio.to_thread(quality, ctx)


def _review_item(r: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        insight_id=r["id"], company_id=r["company_id"], event_id=r["event_id"], headline=r["headline"],
        status=r["status"], confidence_level=r["confidence_level"], supported_share=r.get("supported_share"),
        removed_claims=int(r.get("removed_claims") or 0), created_at=parse_dt(r["created_at"]), review_note=r.get("review_note"),
    )  # fmt: skip


@admin.post("/ingest/run")
async def admin_ingest(
    ctx: AppContext = Depends(get_ctx), runner: JobRunner = Depends(get_runner)
) -> dict[str, bool]:
    jobs = WorkerJobs(ctx, runner)

    async def go() -> None:
        await jobs.rss_fetch()
        await jobs.pipeline_tick()

    runner.spawn_background(go())
    return {"started": True}


@admin.post("/rank/run")
async def admin_rank(ctx: AppContext = Depends(get_ctx)) -> dict[str, int]:
    return {"rows": await asyncio.to_thread(ctx.ranking.rank_all)}


@admin.post("/precompute/run")
async def admin_precompute(
    body: PrecomputeIn, ctx: AppContext = Depends(get_ctx), runner: JobRunner = Depends(get_runner)
) -> dict[str, int]:
    queued = await asyncio.to_thread(enqueue_precompute, ctx, companies=body.companies, top_k=body.top_k)
    runner.spawn_background(runner.process_queue())
    return {"queued": queued}


@admin.get("/review-queue", response_model=list[ReviewItem])
async def review_queue(ctx: AppContext = Depends(get_ctx)) -> list[ReviewItem]:
    return [_review_item(r) for r in QualityStore(ctx.db).review_queue()]


@admin.post("/insights/{insight_id}/review", response_model=ReviewItem)
async def review_insight(insight_id: str, body: ReviewIn, ctx: AppContext = Depends(get_ctx)) -> ReviewItem:
    row = InsightStore(ctx.db).review(insight_id, body.status, body.note)
    if row is None:
        raise NotFoundError("Инсайт не найден", {"insight_id": insight_id})
    return ReviewItem(
        insight_id=row.id, company_id=row.company_id, event_id=row.event_id, headline=row.headline, status=row.status,
        confidence_level=row.confidence_level, supported_share=row.verification.get("supported_share"),
        removed_claims=int(row.payload.get("verification", {}).get("removed_claims", 0)),
        created_at=parse_dt(row.created_at), review_note=row.review_note,
    )  # fmt: skip


@admin.get("/sources/status", response_model=dict[str, SourceStatus])
async def sources_status(ctx: AppContext = Depends(get_ctx)) -> dict[str, SourceStatus]:
    out = {}
    for src in ctx.sources.sources:
        raw = ctx.kv.get(f"source_status:{src.id}", {}) or {}
        out[src.id] = SourceStatus(**{k: v for k, v in raw.items() if k in SourceStatus.model_fields})
    return out
