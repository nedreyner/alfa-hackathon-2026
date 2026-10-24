from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx2
import pytest
from pydantic import BaseModel, Field

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.errors import BudgetExceeded, LLMInvalidOutput, LLMReplayMiss
from alfa_insight.llm.budget import BudgetGuard
from alfa_insight.llm.cache import LLMCache
from alfa_insight.llm.client import GatewayClient
from alfa_insight.llm.router import LiveBackend, LLMRouter, ReplayBackend
from alfa_insight.llm.types import LLMCallRecord, LLMRequest, Message, ModelConfig, ModelsConfig
from alfa_insight.store.llm import LLMStore
from alfa_insight.timeutil import budget_day

PRIMARY = "https://primary.test/v1"
FALLBACK = "https://fallback.test/v1"


def make_config(caps: dict[str, Any] | None = None) -> ModelsConfig:
    return ModelsConfig.model_validate(
        {
            "gateway": {"retries": 2, "retry_delays_s": [0, 0]},
            "default_price_rub_per_1m": {"input": 100, "output": 400},
            "models": {
                "a": {
                    "id": "vendor/a",
                    "family": "fa",
                    "capabilities": {"tools": True} if caps is None else caps,
                },
                "b": {"id": "vendor/b", "family": "fb", "capabilities": {"json_object": True}},
            },
            "tasks": {
                "draft": {"chain": ["a", "b"], "max_tokens": 100, "priority": "precompute"},
                "verify": {"chain": ["a", "b"], "max_tokens": 100, "exclude_drafter_family": True},
                "chat": {"chain": ["a"], "max_tokens": 100, "priority": "interactive", "cache": False},
            },
        }
    )


def ok_body(
    content: str | None = "ответ", tool: tuple[str, dict[str, Any]] | None = None, cost: float | None = 0.01
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool:
        message["tool_calls"] = [
            {"id": "c1", "type": "function", "function": {"name": tool[0], "arguments": json.dumps(tool[1])}}
        ]
    usage: dict[str, Any] = {"prompt_tokens": 10, "completion_tokens": 5}
    if cost is not None:
        usage["cost"] = cost
    return {
        "id": "x",
        "object": "chat.completion",
        "created": 0,
        "model": "vendor/a",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": usage,
    }


Handler = Callable[[httpx2.Request], httpx2.Response]


class MockGateway:
    """Подмена шлюза: маршруты по хосту (`primary.test`, `fallback.test`), счётчики вызовов."""

    def __init__(self) -> None:
        self.routes: dict[str, Handler] = {}
        self.calls: dict[str, int] = {}

    def route(self, host: str, handler: Handler | httpx2.Response | list[httpx2.Response]) -> None:
        if isinstance(handler, httpx2.Response):
            response = handler
            self.routes[host] = lambda _req: response
        elif isinstance(handler, list):
            queue = list(handler)
            self.routes[host] = lambda _req: queue.pop(0)
        else:
            self.routes[host] = handler

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        self.calls[host] = self.calls.get(host, 0) + 1
        if host not in self.routes:
            raise httpx2.ConnectError("нет маршрута", request=request)
        return self.routes[host](request)


def resp(status: int, body: Any = None, headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(
        status, json=body if body is not None else {"error": {"message": "err"}}, headers=headers
    )


class Env:
    def __init__(self, tmp: Path, config: ModelsConfig, *, fallback: bool = True, mode: str = "live"):
        self.gw = MockGateway()
        self.db = SqliteDB(tmp / "app.sqlite")
        self.db.migrate()
        self.store = LLMStore(self.db)
        self.budget = BudgetGuard(
            self.store, daily_limit_rub=450, interactive_reserve_rub=150, max_run_cost_rub=5
        )
        client = GatewayClient(
            PRIMARY, FALLBACK if fallback else None, "k", 5, 2, transport=httpx2.MockTransport(self.gw)
        )
        backend = ReplayBackend() if mode == "replay" else LiveBackend(client)
        self.records: list[LLMCallRecord] = []
        self.router = LLMRouter(
            config, backend, LLMCache(self.store), self.budget, mode=mode, on_call=self.records.append
        )

    def req(self, **kw: Any) -> LLMRequest:
        base: dict[str, Any] = {
            "task": "draft",
            "messages": [Message(role="user", content="привет")],
            "prompt_version": "draft_v1",
        }
        base.update(kw)
        return LLMRequest(**base)


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path, make_config())


async def test_retry_on_429_then_ok(env: Env) -> None:
    env.gw.route("primary.test", [resp(429, headers={"retry-after": "0"}), resp(200, ok_body())])
    res = await env.router.complete(env.req())
    assert res.content == "ответ" and res.model_key == "a" and env.gw.calls["primary.test"] == 2
    assert res.usage.cost_rub == pytest.approx(0.01)
    assert env.records[-1].status == "ok"


async def test_503_switches_to_fallback_url(env: Env) -> None:
    env.gw.route("primary.test", resp(503))
    env.gw.route("fallback.test", resp(200, ok_body()))
    res = await env.router.complete(env.req())
    assert res.base_url_kind == "fallback" and env.gw.calls["fallback.test"] == 1 and res.model_key == "a"
    assert env.gw.calls["primary.test"] == 1  # на запасной адрес — сразу, без ретрая основного


async def test_next_model_after_retries(tmp_path: Path) -> None:
    env = Env(tmp_path, make_config(), fallback=False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        if body["model"] == "vendor/a":
            return resp(503)
        return resp(200, ok_body("от b"))

    env.gw.route("primary.test", handler)
    res = await env.router.complete(env.req())
    assert res.model_key == "b" and res.fallback_model_used and res.content == "от b"
    assert env.gw.calls["primary.test"] == 3 + 1  # 1 + 2 ретрая на модели a, затем b
    assert [r.status for r in env.records] == ["error", "ok"]


async def test_no_retry_on_400(tmp_path: Path) -> None:
    env = Env(tmp_path, make_config(), fallback=False)
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        return resp(400) if model == "vendor/a" else resp(200, ok_body())

    env.gw.route("primary.test", handler)
    await env.router.complete(env.req())
    assert seen == ["vendor/a", "vendor/b"]


async def test_token_param_switch(tmp_path: Path) -> None:
    env = Env(tmp_path, make_config(), fallback=False)
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "max_tokens" in body:
            return resp(
                400,
                {"error": {"message": "Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens'"}},
            )
        return resp(200, ok_body())

    env.gw.route("primary.test", handler)
    await env.router.complete(env.req())
    assert "max_completion_tokens" in bodies[-1] and len(bodies) == 2
    await env.router.complete(env.req(prompt_version="draft_v2"))
    assert "max_completion_tokens" in bodies[-1] and len(bodies) == 3  # выбор запомнен


def _spend(store: LLMStore, amount: float, run_id: str | None = None, day: str | None = None) -> None:
    store.record_call(
        LLMCallRecord(
            ts="2026-10-23T10:00:00Z",
            budget_day=day or budget_day().isoformat(),
            task="draft",
            model="a",
            priority="precompute",
            run_id=run_id,
            cached=False,
            status="ok",
            cost_rub=amount,
        )
    )


def test_budget_reserve_modes_and_run_limit(env: Env) -> None:
    b = env.budget
    assert b.mode() == "normal"
    _spend(env.store, 310)
    b.invalidate()
    with pytest.raises(BudgetExceeded) as exc:
        b.check("background", 1.0)
    assert exc.value.scope == "reserve"
    b.check("interactive", 1.0)
    assert b.mode() == "economy"
    _spend(env.store, 140)
    b.invalidate()
    assert b.mode() == "exhausted"
    with pytest.raises(BudgetExceeded):
        b.check("interactive", 1.0)
    _spend(env.store, 1000, day="2000-01-01")  # другие сутки не считаются
    b.invalidate()
    assert b.spent() == pytest.approx(450)


def test_budget_run_limit(env: Env) -> None:
    _spend(env.store, 4.9, run_id="run_1")
    with pytest.raises(BudgetExceeded) as exc:
        env.budget.check("interactive", 0.2, run_id="run_1")
    assert exc.value.scope == "run"
    env.budget.check("interactive", 0.2, run_id="run_2")


async def test_budget_blocks_before_call(env: Env) -> None:
    env.gw.route("primary.test", resp(200, ok_body()))
    _spend(env.store, 449.99)
    env.budget.invalidate()
    with pytest.raises(BudgetExceeded):
        await env.router.complete(env.req())
    assert env.gw.calls.get("primary.test", 0) == 0 and env.records[-1].status == "budget_blocked"


async def test_cache_hit_and_key_stability(env: Env) -> None:
    env.gw.route("primary.test", resp(200, ok_body()))
    first = await env.router.complete(env.req())
    second = await env.router.complete(env.req())
    assert env.gw.calls["primary.test"] == 1 and not first.cached and second.cached
    assert second.usage.cost_rub == 0 and second.content == first.content
    rows = env.db.query("SELECT cached, cost_rub FROM llm_calls ORDER BY id")
    assert [(r["cached"], r["cost_rub"]) for r in rows] == [(0, pytest.approx(0.01)), (1, 0.0)]
    await env.router.complete(env.req(prompt_version="draft_v2"))
    assert env.gw.calls["primary.test"] == 2  # другая версия промпта — другой ключ
    assert env.store.cache_stats()[0]["entries"] == 2


async def test_chat_not_cached_and_replay_miss(tmp_path: Path) -> None:
    env = Env(tmp_path, make_config(), mode="replay")
    with pytest.raises(LLMReplayMiss):
        await env.router.complete(env.req())


def test_exclude_family_and_chain(env: Env) -> None:
    assert [m.key for m in env.router.chain("verify", ["fa"])] == ["b"]
    with pytest.raises(Exception, match="цепочка пуста"):
        env.router.chain("chat", ["fa"])


# ── структурированный вывод ──
class Answer(BaseModel):
    """Ответ."""

    answer: str = Field(min_length=2)
    score: int


class Scripted:
    def __init__(self, replies: list[dict[str, Any]]):
        self.replies = list(replies)
        self.payloads: list[dict[str, Any]] = []

    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], Literal["primary"]]:
        self.payloads.append({**payload, "model": model.key})
        return self.replies.pop(0), "primary"


def scripted_router(tmp_path: Path, replies: list[dict[str, Any]], **caps: Any) -> tuple[LLMRouter, Scripted]:
    db = SqliteDB(tmp_path / "s.sqlite")
    db.migrate()
    store = LLMStore(db)
    backend = Scripted(replies)
    router = LLMRouter(
        make_config(caps),
        backend,
        LLMCache(store),
        BudgetGuard(store, daily_limit_rub=450, interactive_reserve_rub=150, max_run_cost_rub=5),
    )
    return router, backend


MSGS = [Message(role="system", content="sys"), Message(role="user", content="q")]


@pytest.mark.parametrize(
    ("caps", "strategy", "reply"),
    [
        ({"tools": True}, "tool_call", ok_body(None, tool=("submit_answer", {"answer": "да", "score": 1}))),
        ({"json_schema": True}, "json_schema", ok_body('{"answer": "да", "score": 1}')),
        ({"json_object": True}, "json_object", ok_body('{"answer": "да", "score": 1}')),
        ({}, "prompt_only", ok_body('Вот ответ: ```json\n{"answer": "да", "score": 1}\n``` готово')),
    ],
)
async def test_structured_strategies(
    tmp_path: Path, caps: dict[str, Any], strategy: str, reply: dict[str, Any]
) -> None:
    router, backend = scripted_router(tmp_path, [reply], **caps)
    res = await router.structured(task="draft", messages=MSGS, schema=Answer, prompt_version="v1")
    assert res.value == Answer(answer="да", score=1) and res.strategy_used == strategy and not res.repaired
    payload = backend.payloads[0]
    if strategy == "tool_call":
        assert payload["tool_choice"]["function"]["name"] == "submit_answer"
    elif strategy == "json_schema":
        assert payload["response_format"]["type"] == "json_schema"
    else:
        assert "answer" in payload["messages"][0]["content"] and "score" in payload["messages"][0]["content"]


async def test_structured_repair_after_invalid_json(tmp_path: Path) -> None:
    router, backend = scripted_router(
        tmp_path, [ok_body('{"answer": "д"'), ok_body('{"answer": "да", "score": 2}')], json_object=True
    )
    res = await router.structured(task="draft", messages=MSGS, schema=Answer, prompt_version="v1")
    assert res.repaired and res.value.score == 2
    repair_msgs = backend.payloads[1]["messages"]
    assert repair_msgs[-2]["role"] == "assistant" and "не прошёл проверку схемы" in repair_msgs[-1]["content"]


async def test_structured_next_model_then_invalid(tmp_path: Path) -> None:
    bad = ok_body("не json")
    router, backend = scripted_router(tmp_path, [bad, bad, bad, bad], json_object=True)
    with pytest.raises(LLMInvalidOutput):
        await router.structured(task="draft", messages=MSGS, schema=Answer, prompt_version="v1")
    assert [p["model"] for p in backend.payloads] == ["a", "a", "b", "b"]


class Delayed:
    """Модель a отвечает через `delay_a` секунд, b — сразу."""

    def __init__(self, delay_a: float):
        self.delay_a = delay_a
        self.started: list[str] = []
        self.cancelled: list[str] = []

    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], Literal["primary"]]:
        self.started.append(model.key)
        try:
            if model.key == "a":
                await asyncio.sleep(self.delay_a)
        except asyncio.CancelledError:
            self.cancelled.append(model.key)
            raise
        return ok_body(json.dumps({"answer": f"от {model.key}", "score": 1})), "primary"


def hedged_router(tmp_path: Path, delay_a: float) -> tuple[LLMRouter, Delayed]:
    cfg = make_config({"json_object": True})
    cfg.tasks["draft"].hedge_after_s = 0.05
    db = SqliteDB(tmp_path / "h.sqlite")
    db.migrate()
    backend = Delayed(delay_a)
    return LLMRouter(cfg, backend, None, None), backend


async def test_structured_hedge_second_model_wins(tmp_path: Path) -> None:
    router, backend = hedged_router(tmp_path, delay_a=1.0)
    res = await router.structured(task="draft", messages=MSGS, schema=Answer, prompt_version="v1")
    assert res.value.answer == "от b" and backend.started == ["a", "b"] and backend.cancelled == ["a"]


async def test_structured_hedge_not_needed_for_fast_model(tmp_path: Path) -> None:
    router, backend = hedged_router(tmp_path, delay_a=0.0)
    res = await router.structured(task="draft", messages=MSGS, schema=Answer, prompt_version="v1")
    assert res.value.answer == "от a" and backend.started == ["a"]
