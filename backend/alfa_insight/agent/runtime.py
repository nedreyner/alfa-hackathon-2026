"""Общий вход прогона агента: трасса, учёт стоимости, выбор режима (docs/08-agent.md §1–2)."""

from __future__ import annotations

import time
from typing import Any

from alfa_insight.agent import fakes as _fakes  # noqa: F401 — обработчики FakeLLM для draft и revise
from alfa_insight.agent import verifier as _verifier  # noqa: F401 — обработчик FakeLLM для verify
from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.pipeline_mode import run_pipeline
from alfa_insight.llm.types import LLMCallRecord
from alfa_insight.store.runs import RunStore


async def run_agent(ctx: AgentContext) -> dict[str, Any]:
    """Выполнить прогон и вернуть результат для `agent_runs.result_json`. Ошибки пробрасываются (их пишет jobs)."""
    runs = RunStore(ctx.app.db)

    def on_call(rec: LLMCallRecord) -> None:
        if rec.run_id != ctx.run_id or rec.cached:
            return
        ctx.cost_rub += rec.cost_rub
        runs.add_usage(ctx.run_id, tokens_in=rec.tokens_in, tokens_out=rec.tokens_out, cost_rub=rec.cost_rub)

    router = ctx.app.router
    router.add_listener(ctx.trace.on_llm_call)
    router.add_listener(on_call)
    started = time.monotonic()
    try:
        ctx.trace.emit("run.started", "plan", "Начинаю разбор события",
                       payload={"kind": ctx.kind, "mode": ctx.mode, "event_id": ctx.event_id})  # fmt: skip
        if ctx.kind == "insight":
            insight = await run_pipeline(ctx)
        else:
            raise NotImplementedError(f"вид прогона {ctx.kind} пока не поддержан")
        duration = int((time.monotonic() - started) * 1000)
        run = runs.get(ctx.run_id)
        cost = round(run.cost_rub if run else ctx.cost_rub, 4)
        result = {
            "insight_id": insight.id,
            "status": insight.status,
            "duration_ms": duration,
            "cost_rub": cost,
        }
        runs.succeed(ctx.run_id, insight_id=insight.id, result=result)
        ctx.trace.emit("run.completed", "finalize", f"Готово за {max(1, round(duration / 1000))} с",
                       payload={"insight_id": insight.id, "duration_ms": duration, "cost_rub": cost})  # fmt: skip
        return result
    finally:
        router.remove_listener(on_call)
        router.remove_listener(ctx.trace.on_llm_call)
