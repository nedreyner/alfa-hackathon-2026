"""Зависимости роутов: контекст приложения, сессия, админ-токен, лимиты частоты."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import Depends, Request

from alfa_insight.api.ratelimit import RateLimiter
from alfa_insight.api.session import COOKIE, SessionData, load
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.services.jobs import JobRunner


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx  # type: ignore[no-any-return]


def get_runner(request: Request) -> JobRunner:
    return request.app.state.runner  # type: ignore[no-any-return]


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter  # type: ignore[no-any-return]


def current_session(request: Request, ctx: AppContext = Depends(get_ctx)) -> SessionData:
    return load(ctx.settings, request.cookies.get(COOKIE))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(name: str, *, by: str = "sid") -> Callable[..., Awaitable[None]]:
    """Зависимость: лимит `name` по sid сессии или по IP (`by="ip"`)."""

    async def dep(request: Request, limiter: RateLimiter = Depends(get_limiter)) -> None:
        if by == "ip":
            key = client_ip(request)
        else:
            ctx: AppContext = request.app.state.ctx
            key = load(ctx.settings, request.cookies.get(COOKIE)).sid
        limiter.hit(name, key)

    return dep


def require_admin(request: Request, ctx: AppContext = Depends(get_ctx)) -> None:
    """X-Admin-Token; пустой ADMIN_TOKEN выключает админку (404)."""
    token = ctx.settings.admin_token.get_secret_value()
    given = request.headers.get("x-admin-token", "")
    if not token or not hmac.compare_digest(token, given):
        raise NotFoundError("Не найдено")
