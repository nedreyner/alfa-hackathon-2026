"""Лента и брифинг роли (docs/09-api.md §4.3)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Query

from alfa_insight.agent.briefs import Brief, build_brief
from alfa_insight.api.deps import current_session, get_ctx
from alfa_insight.api.routes.system import budget_mode
from alfa_insight.api.schemas import FeedItem, FeedResponse
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.services.feed import build_feed
from alfa_insight.timeutil import utc_now

router = APIRouter(tags=["feed"])


@router.get("/feed", response_model=FeedResponse)
async def feed(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=64),
    direction: Literal["risk", "opportunity", "mixed"] | None = None,
    min_impact: Literal["low", "medium", "high", "critical"] | None = None,
    s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> FeedResponse:
    page = await asyncio.to_thread(
        build_feed,
        ctx,
        s.company_id,
        s.role,
        limit=limit,
        cursor=cursor,
        direction=direction,
        min_impact=min_impact,
    )
    return FeedResponse(
        items=[FeedItem(**i) for i in page.items], next_cursor=page.next_cursor, total=page.total,
        generated_at=utc_now(), budget_mode=budget_mode(ctx),  # type: ignore[arg-type]
    )  # fmt: skip


@router.get("/brief", response_model=Brief)
async def brief(s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)) -> Brief:
    return await asyncio.to_thread(build_brief, ctx, s.company_id, s.role)
