"""Единый формат ошибок API: {"error": {"code", "message", "details"}} (docs/09-api.md §6)."""

from __future__ import annotations

import math
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from alfa_insight.errors import AppError, BudgetExceeded, LLMError, RateLimited
from alfa_insight.log import get_logger

log = get_logger("api.errors")
HTTP_CODES = {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "bad_request",
              409: "conflict", 429: "rate_limited", 503: "not_ready"}  # fmt: skip


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def _status(exc: AppError) -> int:
    if isinstance(exc, BudgetExceeded):
        return 503
    if isinstance(exc, LLMError):
        return 503
    return exc.http_status


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    status = _status(exc)
    headers = {}
    if isinstance(exc, RateLimited):
        headers["Retry-After"] = str(max(1, math.ceil(exc.retry_after_s)))
    if status >= 500:
        log.warning("api_app_error", path=request.url.path, code=exc.code, error=exc.message)
    return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=status, headers=headers)


async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(
        error_body("validation_error", "Некорректные данные запроса", {"errors": errors}), status_code=422
    )


async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = HTTP_CODES.get(exc.status_code, "internal" if exc.status_code >= 500 else "bad_request")
    message = exc.detail if isinstance(exc.detail, str) else "Ошибка запроса"
    if exc.status_code == 404 and message == "Not Found":
        message = "Не найдено"
    return JSONResponse(error_body(code, message), status_code=exc.status_code, headers=exc.headers)


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("api_unhandled", path=request.url.path)
    return JSONResponse(error_body("internal", "Внутренняя ошибка"), status_code=500)


def install(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_handler)
