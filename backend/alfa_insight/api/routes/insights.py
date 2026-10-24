"""Инсайт, инсайт по событию, трасса, обратная связь (docs/09-api.md §4.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from alfa_insight.api.deps import current_session, get_ctx, rate_limit
from alfa_insight.api.schemas import (
    FeedbackIn,
    FeedbackOut,
    InsightDetailResponse,
    RunInfo,
    TraceEventOut,
    TraceResponse,
)
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.errors import InsightNotReady, NotFoundError
from alfa_insight.services.insights import InsightView, current_prompt_version, get_insight
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.runs import RunRow, RunStore
from alfa_insight.store.telemetry import FeedbackStore
from alfa_insight.timeutil import parse_dt

router = APIRouter(tags=["insights"])


def run_info(ctx: AppContext, run: RunRow) -> RunInfo:
    message_id = None
    if run.kind == "chat" and run.result:
        message_id = run.result.get("message_id")
    return RunInfo(
        id=run.id, kind=run.kind, mode=run.mode, status=run.status, event_id=run.event_id, insight_id=run.insight_id,
        message_id=message_id, error_code=run.error_code, error_message=run.error_message,
        created_at=parse_dt(run.created_at), started_at=parse_dt(run.started_at) if run.started_at else None,
        finished_at=parse_dt(run.finished_at) if run.finished_at else None, duration_ms=run.duration_ms,
        cost_rub=round(run.cost_rub, 4),
    )  # fmt: skip


def detail(ctx: AppContext, view: InsightView, s: SessionData) -> InsightDetailResponse:
    fb = FeedbackStore(ctx.db).get(view.insight.id, s.sid)
    return InsightDetailResponse(
        insight=view.insight, my_feedback=FeedbackOut(**fb) if fb else None, stale=view.stale
    )


@router.get("/insights/{insight_id}", response_model=InsightDetailResponse)
async def get_insight_detail(
    insight_id: str, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> InsightDetailResponse:
    return detail(ctx, get_insight(ctx, insight_id, s.company_id), s)


def visible_event(ctx: AppContext, event_id: int, company_id: str) -> None:
    ev = EventStore(ctx.db).get(event_id)
    if ev is None or (ev.visibility == "private" and ev.owner_company_id != company_id):
        raise NotFoundError("Событие не найдено", {"event_id": event_id})


@router.get(
    "/events/{event_id}/insight",
    response_model=InsightDetailResponse,
    responses={404: {"description": "insight_not_ready"}},
)
async def get_event_insight(
    event_id: int, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> InsightDetailResponse:
    visible_event(ctx, event_id, s.company_id)
    row = InsightStore(ctx.db).latest_for(s.company_id, event_id, prompt_version=current_prompt_version(ctx))
    if row is None:
        run = RunStore(ctx.db).latest_by_events(s.company_id, [event_id]).get(event_id)
        raise InsightNotReady(
            "Разбор ещё не готов", {"run_id": run.id if run else None, "event_id": event_id}
        )
    return detail(ctx, get_insight(ctx, row.id, s.company_id), s)


@router.get("/insights/{insight_id}/trace", response_model=TraceResponse)
async def get_trace(
    insight_id: str, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> TraceResponse:
    view = get_insight(ctx, insight_id, s.company_id)
    runs = RunStore(ctx.db)
    run = runs.get(view.insight.trace_id)
    if run is None or run.company_id != s.company_id:
        raise NotFoundError("Трасса не найдена", {"insight_id": insight_id})
    return TraceResponse(
        run=run_info(ctx, run), events=[TraceEventOut(**t.model_dump()) for t in runs.trace(run.id)]
    )


@router.post(
    "/insights/{insight_id}/feedback", response_model=FeedbackOut, dependencies=[Depends(rate_limit("write"))]
)
async def post_feedback(
    insight_id: str,
    body: FeedbackIn,
    s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> FeedbackOut:
    get_insight(ctx, insight_id, s.company_id)
    fb = FeedbackStore(ctx.db).upsert(
        insight_id=insight_id, company_id=s.company_id, role=s.role, session_id=s.sid, useful=body.useful,
        reason=body.reason, comment=body.comment,
    )  # fmt: skip
    return FeedbackOut(**fb)
