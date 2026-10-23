"""Кеш LLM-ответов (docs/04-llm.md §6). Ключ — sha256 канонического запроса без конкретной модели."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson

from alfa_insight.store.llm import LLMStore

CACHE_KEY_VERSION = 1


def canonical_request(
    *,
    task: str,
    chain: list[str],
    prompt_version: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    tool_choice: Any,
    response_format: dict[str, Any] | None,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    return {
        "v": CACHE_KEY_VERSION,
        "task": task,
        "chain": chain,
        "prompt_version": prompt_version,
        "messages": messages,
        "tools": tools,
        "tool_choice": tool_choice,
        "response_format": response_format,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def cache_key(request: dict[str, Any]) -> str:
    return hashlib.sha256(orjson.dumps(request, option=orjson.OPT_SORT_KEYS)).hexdigest()


class LLMCache:
    def __init__(self, store: LLMStore):
        self.store = store

    def get(self, key: str) -> dict[str, Any] | None:
        hit = self.store.cache_get(key)
        if hit is not None:
            self.store.cache_hit(key)
        return hit

    def put(
        self,
        key: str,
        *,
        task: str,
        model: str,
        prompt_version: str,
        request: dict[str, Any],
        response: dict[str, Any],
        tokens_in: int,
        tokens_out: int,
        cost_rub: float,
    ) -> None:
        self.store.cache_put(
            key,
            task=task,
            model=model,
            prompt_version=prompt_version,
            request=request,
            response=response,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_rub=cost_rub,
        )
