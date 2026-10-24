"""Вход, сессия, смена роли, выход (docs/09-api.md §2)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Response

from alfa_insight.api.deps import current_session, get_ctx, rate_limit
from alfa_insight.api.routes.companies import company_summary
from alfa_insight.api.routes.system import budget_mode
from alfa_insight.api.schemas import SessionCreate, SessionInfo, SessionUpdate
from alfa_insight.api.session import SessionData, clear_cookie, set_cookie
from alfa_insight.appctx import AppContext
from alfa_insight.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["session"])


def session_info(ctx: AppContext, s: SessionData) -> SessionInfo:
    return SessionInfo(
        company=company_summary(ctx, s.company_id), role=s.role, jury=s.jury, demo_mode=ctx.settings.demo_mode,
        budget_mode=budget_mode(ctx),  # type: ignore[arg-type]
    )  # fmt: skip


@router.post("/session", response_model=SessionInfo, dependencies=[Depends(rate_limit("session", by="ip"))])
async def create_session(
    body: SessionCreate, response: Response, ctx: AppContext = Depends(get_ctx)
) -> SessionInfo:
    if not ctx.profiles.exists(body.company_id):
        raise NotFoundError("Компания не найдена", {"company_id": body.company_id})
    jury = False
    code = ctx.settings.jury_code.get_secret_value()
    if body.jury_code:
        if not code or not hmac.compare_digest(code, body.jury_code):
            raise ForbiddenError("Неверный код жюри")
        jury = True
    if not ctx.settings.demo_mode and not jury and body.company_id not in ctx.demo.ids():
        raise ForbiddenError("Вход в эту компанию доступен по коду жюри")
    data = SessionData.new(body.company_id, body.role, jury=jury)
    set_cookie(response, ctx.settings, data)
    return session_info(ctx, data)


@router.get("/session", response_model=SessionInfo)
async def get_session(
    s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> SessionInfo:
    return session_info(ctx, s)


@router.patch("/session", response_model=SessionInfo)
async def update_session(
    body: SessionUpdate,
    response: Response,
    s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> SessionInfo:
    data = s.model_copy(update={"role": body.role})
    set_cookie(response, ctx.settings, data)
    return session_info(ctx, data)


@router.delete("/session", status_code=204, response_class=Response)
async def delete_session(response: Response, ctx: AppContext = Depends(get_ctx)) -> Response:
    out = Response(status_code=204)
    clear_cookie(out, ctx.settings)
    return out
