"""LLMRouter: цепочки моделей, кеш, бюджет, ретраи, структурированный вывод (docs/04-llm.md §4–§8)."""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from alfa_insight.errors import (
    BudgetExceeded,
    ConfigError,
    LLMInvalidOutput,
    LLMReplayMiss,
    LLMUnavailable,
)
from alfa_insight.llm.budget import BudgetGuard, estimate_cost
from alfa_insight.llm.cache import LLMCache, cache_key, canonical_request
from alfa_insight.llm.client import GatewayClient, GatewayError
from alfa_insight.llm.fake import FAKE_MODEL
from alfa_insight.llm.structured import (
    choose_strategy,
    extract_json_block,
    json_instruction,
    repair_message,
    to_llm_schema,
    tool_name,
)
from alfa_insight.llm.types import (
    BaseUrlKind,
    LLMCallRecord,
    LLMRequest,
    LLMResult,
    Message,
    ModelCapabilities,
    ModelConfig,
    ModelsConfig,
    Priority,
    Strategy,
    StructuredResult,
    TaskConfig,
    TaskName,
    ToolCall,
    ToolSpec,
    Usage,
)
from alfa_insight.log import get_logger
from alfa_insight.timeutil import budget_day, to_iso, utc_now

log = get_logger("llm.router")
CallListener = Callable[[LLMCallRecord], None]
MAX_RETRY_AFTER_S = 10.0


class LLMBackend(Protocol):
    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], BaseUrlKind | None]: ...


class LiveBackend:
    def __init__(self, client: GatewayClient):
        self.client = client

    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], BaseUrlKind | None]:
        response, kind = await self.client.chat(model.id, payload, timeout_s)
        return response, kind


class ReplayBackend:
    async def call(
        self, model: ModelConfig, payload: dict[str, Any], timeout_s: float, request: LLMRequest
    ) -> tuple[dict[str, Any], BaseUrlKind | None]:
        raise LLMReplayMiss(f"нет ответа в кеше для задачи {request.task}", {"task": request.task})


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tc in raw or []:
        fn = tc.get("function") or {}
        args_raw = fn.get("arguments")
        try:
            args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            if not isinstance(args, dict):
                args = {"__raw__": args_raw}
        except json.JSONDecodeError:
            args = {"__raw__": args_raw}
        calls.append(
            ToolCall(id=tc.get("id") or f"call_{len(calls)}", name=fn.get("name", ""), arguments=args)
        )
    return calls


def _message_dict(m: Message) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role}
    if isinstance(m.content, list):
        d["content"] = [p.model_dump() for p in m.content]
    else:
        d["content"] = m.content
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    return d


class LLMRouter:
    def __init__(
        self,
        config: ModelsConfig,
        backend: LLMBackend,
        cache: LLMCache | None,
        budget: BudgetGuard | None,
        *,
        mode: str = "live",
        on_call: CallListener | None = None,
        capabilities_override: dict[str, dict[str, Any]] | None = None,
        budget_tz: str = "Europe/Moscow",
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.backend = backend
        self.cache = cache
        self.budget = budget
        self.mode = mode
        self.budget_tz = budget_tz
        self._listeners: list[CallListener] = [on_call] if on_call else []
        self._caps_override = capabilities_override or {}
        self._sleep = sleep
        self._token_param: dict[str, str] = {}
        g = config.gateway
        self._sem = {
            "interactive": asyncio.Semaphore(g.max_concurrency_interactive),
            "other": asyncio.Semaphore(g.max_concurrency_background),
        }
        for name, task in config.tasks.items():
            if task.exclude_drafter_family:
                self.chain(name)  # type: ignore[arg-type]

    # ── слушатели вызовов (трасса агента, учёт) ──
    def add_listener(self, fn: CallListener) -> None:
        self._listeners.append(fn)

    def remove_listener(self, fn: CallListener) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    @property
    def is_fake(self) -> bool:
        return self.mode == "fake"

    # ── конфигурация ──
    def task(self, name: TaskName) -> TaskConfig:
        try:
            return self.config.tasks[name]
        except KeyError as exc:
            raise ConfigError(f"задача {name!r} не описана в models.yaml") from exc

    def chain(self, task: TaskName, exclude_families: list[str] | None = None) -> list[ModelConfig]:
        excl = set(exclude_families or [])
        models = [self.config.models[k] for k in self.task(task).chain]
        result = [m for m in models if m.family not in excl]
        if not result:
            raise ConfigError(f"задача {task}: после исключения семейств {sorted(excl)} цепочка пуста")
        return result

    def capabilities(self, model_key: str) -> ModelCapabilities:
        if self.is_fake:
            return ModelCapabilities(tools=True, json_schema=True, json_object=True, vision=True, usage=True)
        base = self.config.models[model_key].capabilities.model_dump()
        override = {k: v for k, v in (self._caps_override.get(model_key) or {}).items() if v is not None}
        return ModelCapabilities.model_validate({**base, **override})

    def _token_param_for(self, model: ModelConfig) -> str:
        return self._token_param.get(model.key) or model.token_param or self.config.gateway.token_param

    # ── учёт ──
    def _record(self, rec: LLMCallRecord) -> None:
        if self.budget is not None:
            self.budget.store.record_call(rec)
            self.budget.invalidate()
        for fn in list(self._listeners):
            try:
                fn(rec)
            except Exception:  # слушатель не должен ломать вызов
                log.exception("llm_listener_failed")

    def _rec(self, req: LLMRequest, priority: Priority, model: str, status: str, **kw: Any) -> LLMCallRecord:
        now = utc_now()
        return LLMCallRecord(
            ts=to_iso(now),
            budget_day=budget_day(now, self.budget_tz).isoformat(),
            task=req.task,
            model=model,
            priority=priority,
            run_id=req.run_id,
            status=status,  # type: ignore[arg-type]
            cached=kw.pop("cached", False),
            **kw,
        )

    # ── основной вызов ──
    def _payload(
        self, req: LLMRequest, model: ModelConfig, temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [_message_dict(m) for m in req.messages],
            "temperature": temperature,
            self._token_param_for(model): max_tokens,
        }
        if req.tools:
            payload["tools"] = [{"type": "function", "function": t.model_dump()} for t in req.tools]
        if req.tool_choice is not None:
            payload["tool_choice"] = req.tool_choice
        if req.response_format is not None:
            payload["response_format"] = req.response_format
        return payload

    def _result(
        self,
        response: dict[str, Any],
        model: ModelConfig,
        *,
        cached: bool,
        latency_ms: int,
        kind: BaseUrlKind | None,
        fallback_model: bool,
    ) -> LLMResult:
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = response.get("usage") or {}
        tokens_in = int(usage.get("prompt_tokens") or 0)
        tokens_out = int(usage.get("completion_tokens") or 0)
        cost = usage.get("cost")
        if cost is None:
            p_in, p_out = self.config.price(model)
            cost = (tokens_in * p_in + tokens_out * p_out) / 1e6
        fake = self.is_fake
        return LLMResult(
            model_key=FAKE_MODEL if fake else model.key,
            model_id=FAKE_MODEL if fake else model.id,
            family=FAKE_MODEL if fake else model.family,
            content=message.get("content"),
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            finish_reason=choice.get("finish_reason"),
            usage=Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_rub=0.0 if cached else float(cost)),
            cached=cached,
            latency_ms=latency_ms,
            base_url_kind=kind,
            fallback_model_used=fallback_model,
        )

    async def _call_with_retries(
        self,
        model: ModelConfig,
        payload: dict[str, Any],
        timeout_s: float,
        req: LLMRequest,
        priority: Priority,
    ) -> tuple[dict[str, Any], BaseUrlKind | None]:
        delays = list(self.config.gateway.retry_delays_s)
        attempts = 1 + self.config.gateway.retries
        switched_param = False
        attempt = 0
        sem = self._sem["interactive" if priority == "interactive" else "other"]
        while True:
            try:
                async with sem:
                    return await self.backend.call(model, payload, timeout_s, req)
            except GatewayError as err:
                if err.status in (400, 422):
                    msg = str(err).lower()
                    current = self._token_param_for(model)
                    other = "max_completion_tokens" if current == "max_tokens" else "max_tokens"
                    if not switched_param and (current in msg or other in msg):
                        switched_param = True
                        payload = {k: v for k, v in payload.items() if k != current} | {
                            other: payload[current]
                        }
                        self._token_param[model.key] = other
                        continue
                    raise
                attempt += 1
                if not err.retryable or attempt >= attempts:
                    raise
                delay = delays[min(attempt - 1, len(delays) - 1)] if delays else 0.0
                delay *= random.uniform(0.8, 1.2)
                if err.status == 429 and err.retry_after is not None:
                    delay = min(err.retry_after, MAX_RETRY_AFTER_S)
                await self._sleep(delay)

    async def complete(self, req: LLMRequest) -> LLMResult:
        tcfg = self.task(req.task)
        temperature = tcfg.temperature if req.temperature is None else req.temperature
        max_tokens = tcfg.max_tokens if req.max_tokens is None else req.max_tokens
        priority: Priority = req.priority or tcfg.priority
        full_chain = self.chain(req.task, req.exclude_families)
        chain = [m for m in full_chain if m.key == req.only_model] if req.only_model else full_chain
        if not chain:
            raise ConfigError(f"модель {req.only_model} не входит в цепочку задачи {req.task}")

        use_cache = self.cache is not None and req.cache and tcfg.cache and not self.is_fake
        canonical = canonical_request(
            task=req.task,
            chain=[m.key for m in full_chain],
            prompt_version=req.prompt_version,
            messages=[_message_dict(m) for m in req.messages],
            tools=[t.model_dump() for t in req.tools] if req.tools else None,
            tool_choice=req.tool_choice,
            response_format=req.response_format,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        key = cache_key(canonical)
        if use_cache:
            assert self.cache is not None
            hit = self.cache.get(key)
            if hit is not None:
                model_key = hit.get("_model_key", chain[0].key)
                model = self.config.models.get(model_key, chain[0])
                result = self._result(hit, model, cached=True, latency_ms=0, kind=None, fallback_model=False)
                result.cache_key = key
                self._record(
                    self._rec(
                        req,
                        priority,
                        model.key,
                        "ok",
                        cached=True,
                        cache_key=key,
                        tokens_in=result.usage.tokens_in,
                        tokens_out=result.usage.tokens_out,
                    )
                )
                return result
        if self.mode == "replay" and not self.is_fake:
            raise LLMReplayMiss(f"нет ответа в кеше для задачи {req.task}", {"task": req.task})

        text_chars = len(json.dumps(canonical["messages"], ensure_ascii=False)) + len(
            json.dumps(canonical["tools"] or [], ensure_ascii=False)
        )
        errors: list[str] = []
        for idx, model in enumerate(chain):
            fallback_model = (full_chain.index(model) if req.only_model else idx) > 0
            if self.budget is not None and not self.is_fake:
                p_in, p_out = self.config.price(model)
                est = estimate_cost(text_chars, max_tokens, p_in, p_out)
                try:
                    self.budget.check(priority, est, req.run_id)
                except BudgetExceeded as exc:
                    self._record(self._rec(req, priority, model.key, "budget_blocked", error=exc.scope))
                    raise
            payload = self._payload(req, model, temperature, max_tokens)
            started = time.monotonic()
            try:
                response, kind = await self._call_with_retries(model, payload, tcfg.timeout_s, req, priority)
            except GatewayError as err:
                latency = int((time.monotonic() - started) * 1000)
                errors.append(f"{model.key}: {err}")
                self._record(
                    self._rec(req, priority, model.key, "error", latency_ms=latency, error=str(err)[:500])
                )
                log.warning("llm_model_failed", model=model.key, task=req.task, status=err.status)
                continue
            latency = int((time.monotonic() - started) * 1000)
            result = self._result(
                response, model, cached=False, latency_ms=latency, kind=kind, fallback_model=fallback_model
            )
            self._record(
                self._rec(
                    req,
                    priority,
                    result.model_key,
                    "ok",
                    tokens_in=result.usage.tokens_in,
                    tokens_out=result.usage.tokens_out,
                    cost_rub=result.usage.cost_rub,
                    latency_ms=latency,
                    base_url_kind=kind,
                    fallback_model_used=fallback_model,
                    cache_key=key if use_cache else None,
                )
            )
            if use_cache:
                assert self.cache is not None
                result.cache_key = key
                self.cache.put(
                    key,
                    task=req.task,
                    model=model.key,
                    prompt_version=req.prompt_version,
                    request=canonical,
                    response={**response, "_model_key": model.key},
                    tokens_in=result.usage.tokens_in,
                    tokens_out=result.usage.tokens_out,
                    cost_rub=result.usage.cost_rub,
                )
            return result
        raise LLMUnavailable("Все модели цепочки недоступны", {"task": req.task, "errors": errors[-5:]})

    # ── структурированный вывод ──
    def _structured_request(
        self,
        base: LLMRequest,
        schema: type[BaseModel],
        llm_schema: dict[str, Any],
        strategy: Strategy,
        model_key: str,
    ) -> LLMRequest:
        messages = list(base.messages)
        req = base.model_copy(update={"only_model": model_key, "schema_hint": llm_schema})
        if strategy == "tool_call":
            name = tool_name(schema)
            req.tools = [
                *(base.tools or []),
                ToolSpec(name=name, description=(schema.__doc__ or name).strip(), parameters=llm_schema),
            ]
            req.tool_choice = {"type": "function", "function": {"name": name}}
        elif strategy == "json_schema":
            req.response_format = {
                "type": "json_schema",
                "json_schema": {"name": schema.__name__, "schema": llm_schema, "strict": False},
            }
        else:
            if strategy == "json_object":
                req.response_format = {"type": "json_object"}
            instruction = json_instruction(llm_schema)
            if messages and messages[0].role == "system":
                messages[0] = Message(role="system", content=f"{messages[0].text()}\n\n{instruction}")
            else:
                messages.insert(0, Message(role="system", content=instruction))
            req.messages = messages
        return req

    def _drop_cached(self, result: LLMResult) -> None:
        """Ответ не прошёл схему — не даём ему отравить кеш (ключ общий для всей цепочки)."""
        if self.cache is not None and result.cache_key:
            self.cache.store.cache_delete(result.cache_key)

    @staticmethod
    def _parse[T: BaseModel](result: LLMResult, schema: type[T], strategy: Strategy) -> T:
        if strategy == "tool_call":
            if not result.tool_calls:
                if result.content:
                    return schema.model_validate(extract_json_block(result.content))
                raise ValueError("модель не вызвала инструмент")
            args = result.tool_calls[0].arguments
            if "__raw__" in args:
                raise ValueError("аргументы инструмента — невалидный JSON")
            return schema.model_validate(args)
        return schema.model_validate(extract_json_block(result.content))

    async def structured[T: BaseModel](
        self,
        *,
        task: TaskName,
        messages: list[Message],
        schema: type[T],
        prompt_version: str,
        priority: Priority | None = None,
        run_id: str | None = None,
        strategy: Strategy | None = None,
        exclude_families: list[str] | None = None,
        cache: bool = True,
        max_tokens: int | None = None,
    ) -> StructuredResult[T]:
        tcfg = self.task(task)
        llm_schema = to_llm_schema(schema)
        base = LLMRequest(
            task=task,
            messages=messages,
            prompt_version=prompt_version,
            priority=priority,
            run_id=run_id,
            cache=cache,
            exclude_families=list(exclude_families or []),
            max_tokens=max_tokens,
        )
        failures: list[str] = []
        replay_miss = False
        invalid = False
        for model in self.chain(task, exclude_families):
            strat = choose_strategy(strategy or tcfg.strategy, self.capabilities(model.key))
            req = self._structured_request(base, schema, llm_schema, strat, model.key)
            try:
                result = await self.complete(req)
            except LLMReplayMiss:
                replay_miss = True
                continue
            except LLMUnavailable as exc:
                failures.append(str(exc))
                continue
            try:
                return StructuredResult[schema](  # type: ignore[valid-type]
                    value=self._parse(result, schema, strat), raw=result, strategy_used=strat, repaired=False
                )
            except (ValueError, ValidationError) as exc:
                first_error: Exception = exc
                self._drop_cached(result)
            raw_text = (
                json.dumps(result.tool_calls[0].arguments, ensure_ascii=False)
                if result.tool_calls
                else (result.content or "")
            )
            repair = req.model_copy(
                update={
                    "messages": [
                        *req.messages,
                        Message(role="assistant", content=raw_text[:8000]),
                        Message(role="user", content=repair_message(first_error)),
                    ]
                }
            )
            fixed: LLMResult | None = None
            try:
                fixed = await self.complete(repair)
                return StructuredResult[schema](  # type: ignore[valid-type]
                    value=self._parse(fixed, schema, strat), raw=fixed, strategy_used=strat, repaired=True
                )
            except LLMReplayMiss:
                replay_miss = True
            except LLMUnavailable as exc:
                failures.append(str(exc))
            except (ValueError, ValidationError) as exc:
                invalid = True
                if fixed is not None:
                    self._drop_cached(fixed)
                failures.append(f"{model.key}: {exc}"[:300])
                self._record(
                    self._rec(
                        base,
                        base.priority or tcfg.priority,
                        result.model_key,
                        "invalid_output",
                        error=str(exc)[:500],
                    )
                )
        if invalid:
            raise LLMInvalidOutput(
                "Модели вернули ответ не по схеме", {"task": task, "errors": failures[-5:]}
            )
        if replay_miss and not failures:
            raise LLMReplayMiss(f"нет ответа в кеше для задачи {task}", {"task": task})
        raise LLMUnavailable("Все модели цепочки недоступны", {"task": task, "errors": failures[-5:]})
