"""Подписанная cookie сессии `ai_session` (docs/09-api.md §2, docs/11-security.md §2)."""

from __future__ import annotations

import secrets
import time

from fastapi import Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel, ValidationError

from alfa_insight.errors import UnauthorizedError
from alfa_insight.ranking.models import Role
from alfa_insight.settings import Settings

COOKIE = "ai_session"
SALT = "ai-session"
MAX_AGE_S = 7 * 24 * 3600


class SessionData(BaseModel):
    sid: str
    company_id: str
    role: Role
    jury: bool
    iat: int

    @classmethod
    def new(cls, company_id: str, role: Role, *, jury: bool) -> SessionData:
        return cls(
            sid=secrets.token_urlsafe(16), company_id=company_id, role=role, jury=jury, iat=int(time.time())
        )


def serializer(settings: Settings) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.session_secret.get_secret_value(), salt=SALT)


def dump(settings: Settings, data: SessionData) -> str:
    return serializer(settings).dumps(data.model_dump())


def load(settings: Settings, token: str | None) -> SessionData:
    if not token:
        raise UnauthorizedError("Нужно войти")
    try:
        raw = serializer(settings).loads(token, max_age=MAX_AGE_S)
        return SessionData.model_validate(raw)
    except (BadSignature, ValidationError, TypeError) as exc:
        raise UnauthorizedError("Сессия недействительна, войдите заново") from exc


def set_cookie(response: Response, settings: Settings, data: SessionData) -> None:
    response.set_cookie(
        COOKIE, dump(settings, data), max_age=MAX_AGE_S, httponly=True, samesite="lax",
        secure=settings.cookie_secure, path="/",
    )  # fmt: skip


def clear_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure)
