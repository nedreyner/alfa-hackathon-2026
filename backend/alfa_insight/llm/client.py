"""Клиент шлюза — единственное место, где импортируется `openai` (docs/04-llm.md §4, §8)."""

from __future__ import annotations

import time
from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI

from alfa_insight.llm.types import BaseUrlKind

FALLBACK_STATUSES = {502, 503, 504}
STICKY_SUCCESSES = 3
STICKY_SECONDS = 600.0


class GatewayError(Exception):
    """Ошибка шлюза: `status` None — сбой соединения или таймаут."""

    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after

    @property
    def retryable(self) -> bool:
        return self.status is None or self.status == 429 or self.status >= 500


def _to_gateway_error(exc: Exception) -> GatewayError:
    if isinstance(exc, openai.APIStatusError):
        retry_after = None
        header = exc.response.headers.get("retry-after") if exc.response is not None else None
        if header:
            try:
                retry_after = float(header)
            except ValueError:
                retry_after = None
        return GatewayError(str(exc.message)[:500], exc.status_code, retry_after)
    if isinstance(exc, openai.APITimeoutError | openai.APIConnectionError):
        return GatewayError(f"{type(exc).__name__}: {exc}"[:500], None)
    return GatewayError(f"{type(exc).__name__}: {exc}"[:500], None)


class GatewayClient:
    def __init__(
        self,
        primary_url: str,
        fallback_url: str | None,
        api_key: str,
        timeout_s: float,
        connect_timeout_s: float,
        token_param: str = "max_tokens",
        transport: Any = None,
    ) -> None:
        """`transport` — подмена HTTP-транспорта в тестах (`httpx2.MockTransport`): openai 3.x работает
        поверх httpx2, поэтому respx его не перехватывает."""
        self.token_param = token_param
        timeout = openai.Timeout(timeout_s, connect=connect_timeout_s)

        def make(url: str) -> AsyncOpenAI:
            http_client = (
                httpx2.AsyncClient(transport=transport, timeout=timeout) if transport is not None else None
            )
            return AsyncOpenAI(
                base_url=url,
                api_key=api_key or "missing",
                max_retries=0,
                timeout=timeout,
                http_client=http_client,
            )

        self._clients: dict[BaseUrlKind, AsyncOpenAI] = {"primary": make(primary_url)}
        if fallback_url:
            self._clients["fallback"] = make(fallback_url)
        self._fallback_streak = 0
        self._sticky_until = 0.0

    @property
    def has_fallback(self) -> bool:
        return "fallback" in self._clients

    def _order(self) -> list[BaseUrlKind]:
        if self.has_fallback and time.monotonic() < self._sticky_until:
            return ["fallback", "primary"]
        return ["primary", "fallback"] if self.has_fallback else ["primary"]

    async def _call(self, kind: BaseUrlKind, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        client = self._clients[kind]
        try:
            resp = await client.chat.completions.create(**payload, timeout=timeout_s)
        except Exception as exc:
            raise _to_gateway_error(exc) from exc
        return resp.model_dump()

    async def chat(
        self, model_id: str, payload: dict[str, Any], timeout_s: float
    ) -> tuple[dict[str, Any], BaseUrlKind]:
        body = {**payload, "model": model_id}
        order = self._order()
        last: GatewayError | None = None
        for i, kind in enumerate(order):
            try:
                result = await self._call(kind, body, timeout_s)
            except GatewayError as err:
                last = err
                switchable = err.status is None or err.status in FALLBACK_STATUSES
                if i + 1 < len(order) and switchable:
                    continue
                if kind == "primary" and self._fallback_streak:
                    self._fallback_streak = 0
                raise
            if kind == "fallback" and i > 0:
                self._fallback_streak += 1
                if self._fallback_streak >= STICKY_SUCCESSES:
                    self._sticky_until = time.monotonic() + STICKY_SECONDS
            elif kind == "primary":
                self._fallback_streak = 0
            return result, kind
        assert last is not None
        raise last

    async def list_models(self) -> dict[BaseUrlKind, list[str]]:
        out: dict[BaseUrlKind, list[str]] = {}
        for kind, client in self._clients.items():
            try:
                page = await client.models.list()
                out[kind] = sorted(m.id for m in page.data)
            except Exception as exc:
                raise _to_gateway_error(exc) from exc
        return out
