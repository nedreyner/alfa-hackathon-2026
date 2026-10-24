"""Доменные исключения. API переводит их в коды ошибок (`docs/09-api.md` §6)."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "internal"
    http_status = 500

    def __init__(self, message: str = "", details: dict[str, Any] | None = None, *, code: str | None = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.details = details or {}
        if code is not None:
            self.code = code

    def __str__(self) -> str:
        return self.message


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class InsightNotReady(NotFoundError):
    code = "insight_not_ready"


class ForbiddenError(AppError):
    code = "forbidden"
    http_status = 403


class UnauthorizedError(AppError):
    code = "unauthorized"
    http_status = 401


class ConflictError(AppError):
    code = "conflict"
    http_status = 409


class ValidationAppError(AppError):
    code = "bad_request"
    http_status = 400


class ConfigError(AppError):
    """Ошибка в YAML-конфиге или справочнике: путь к файлу и поле — в сообщении."""

    code = "internal"


class RateLimited(AppError):
    code = "rate_limited"
    http_status = 429

    def __init__(self, message: str = "Слишком много запросов", retry_after_s: float = 1.0, **kw: Any):
        super().__init__(message, {"retry_after_s": retry_after_s}, **kw)
        self.retry_after_s = retry_after_s


class Busy(AppError):
    code = "busy"
    http_status = 429


class BlockedUrl(AppError):
    code = "blocked_url"
    http_status = 400


class FetchFailed(AppError):
    code = "fetch_failed"
    http_status = 400


class UnsupportedContent(AppError):
    code = "unsupported_content"
    http_status = 400


class LLMError(AppError):
    code = "llm_error"
    http_status = 503


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMInvalidOutput(LLMError):
    code = "llm_invalid_output"


class LLMReplayMiss(LLMError):
    code = "llm_replay_miss"


class BudgetExceeded(LLMError):
    code = "budget_exhausted"

    def __init__(self, scope: str, message: str = "", **kw: Any):
        super().__init__(message or f"Бюджет исчерпан ({scope})", {"scope": scope}, **kw)
        self.scope = scope
