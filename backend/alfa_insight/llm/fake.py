"""FakeBackend: детерминированные валидные ответы без сети (docs/04-llm.md §9).

Обработчики задач регистрируются декоратором `@fake_handler("tagging")` в модулях, где живёт логика
(разметка, агент, проверка). Без обработчика ответ строится из JSON Schema запроса.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from alfa_insight.llm.types import LLMRequest, ModelConfig

FAKE_MODEL = "fake"


@dataclass
class FakeReply:
    content: str | None = None
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


FakeHandler = Callable[[LLMRequest, dict[str, Any]], "FakeReply | dict[str, Any] | None"]
_HANDLERS: dict[str, FakeHandler] = {}


def fake_handler(*tasks: str) -> Callable[[FakeHandler], FakeHandler]:
    def deco(fn: FakeHandler) -> FakeHandler:
        for t in tasks:
            _HANDLERS[t] = fn
        return fn

    return deco


def registered_tasks() -> list[str]:
    return sorted(_HANDLERS)


def example_from_schema(schema: dict[str, Any]) -> Any:
    """Минимальный экземпляр по JSON Schema: только обязательные поля, первые значения enum."""
    if "enum" in schema:
        values = [v for v in schema["enum"] if v is not None]
        return values[0] if values else None
    t = schema.get("type")
    types = t if isinstance(t, list) else [t]
    types = [x for x in types if x != "null"] or [None]
    base = types[0]
    if base == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {
            name: example_from_schema(props[name]) for name in schema.get("required", []) if name in props
        }
    if base == "array":
        n = int(schema.get("minItems", 0))
        return [example_from_schema(schema.get("items", {})) for _ in range(n)]
    if base == "integer":
        return int(schema.get("minimum", 0))
    if base == "number":
        return float(schema.get("minimum", 0.0))
    if base == "boolean":
        return False
    if base == "string":
        n = int(schema.get("minLength", 0))
        return "fake" if n <= 4 else "f" * n
    return None


def forced_tool(payload: dict[str, Any]) -> dict[str, Any] | None:
    choice = payload.get("tool_choice")
    tools = payload.get("tools") or []
    if isinstance(choice, dict):
        name = choice.get("function", {}).get("name")
        return next((t["function"] for t in tools if t["function"]["name"] == name), None)
    return None


def _schema_of(request: LLMRequest, payload: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    tool = forced_tool(payload)
    if tool is not None:
        return tool["name"], tool["parameters"]
    rf = payload.get("response_format") or {}
    if rf.get("type") == "json_schema":
        return None, rf["json_schema"]["schema"]
    return None, request.schema_hint


def _tokens(payload: dict[str, Any]) -> int:
    return max(1, len(json.dumps(payload.get("messages", []), ensure_ascii=False)) // 3)


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], None]:
        self.calls.append((request.task, payload))
        handler = _HANDLERS.get(request.task)
        reply = handler(request, payload) if handler else None
        tool_name, schema = _schema_of(request, payload)
        if reply is None:
            reply = example_from_schema(schema) if schema is not None else FakeReply(content="fake")
        if isinstance(reply, dict):
            if tool_name:
                reply = FakeReply(tool_calls=[(tool_name, reply)])
            else:
                reply = FakeReply(content=json.dumps(reply, ensure_ascii=False))
        assert isinstance(reply, FakeReply)
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[
            :12
        ]
        message: dict[str, Any] = {"role": "assistant", "content": reply.content}
        if reply.tool_calls:
            message["tool_calls"] = [
                {
                    "id": f"call_{digest}_{i}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }
                for i, (name, args) in enumerate(reply.tool_calls)
            ]
        out_tokens = max(1, len(json.dumps(message, ensure_ascii=False)) // 3)
        return (
            {
                "id": f"fake-{digest}",
                "object": "chat.completion",
                "model": FAKE_MODEL,
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "tool_calls" if reply.tool_calls else "stop",
                        "message": message,
                    }
                ],
                "usage": {"prompt_tokens": _tokens(payload), "completion_tokens": out_tokens, "cost": 0.0},
            },
            None,
        )
