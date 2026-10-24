"""Режим agentic: модель сама планирует и вызывает инструменты, затем submit_insight (docs/08-agent.md §7)."""

from __future__ import annotations

import asyncio
import json

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.evidence import KIND_LABELS
from alfa_insight.agent.pipeline_mode import (
    ROLE_TEXT,
    collect_base,
    draft_and_verify,
    expected_impact,
    finish,
)
from alfa_insight.agent.render import chain_block, evidence_block, profile_brief
from alfa_insight.agent.schemas import Insight, InsightDraft, VerificationReport
from alfa_insight.agent.tools import execute_tool_call, result_for_model, tool_specs
from alfa_insight.agent.verifier import inputs_from_context, verify
from alfa_insight.errors import BudgetExceeded, LLMInvalidOutput
from alfa_insight.llm.types import LLMRequest, LLMResult, Message, ToolCall
from alfa_insight.products.catalog import ProductCandidate, products_block

AGENT_TOOLS = [
    "get_event", "get_counterparties", "search_news", "search_alfa_research", "get_macro",
    "get_related_group", "submit_insight",
]  # fmt: skip
NUDGE = "Вызови submit_insight с готовым InsightDraft."
THOUGHT_CHARS = 600
PLAN_LABELS = {
    "get_event": "материалы события",
    "get_counterparties": "ключевых контрагентов",
    "search_news": "связанные новости",
    "search_alfa_research": "позицию аналитиков банка",
    "get_macro": "макроданные ЦБ",
    "get_related_group": "компании группы",
}


def agent_prompt_version(ctx: AgentContext) -> str:
    p = ctx.app.prompts
    return f"{p.version('agent')}+{p.version('verify')}"


def tools_supported(ctx: AgentContext) -> bool:
    router = ctx.app.router
    return any(router.capabilities(m.key).tools for m in router.chain("agent"))


def _plan_from_calls(calls: list[ToolCall]) -> str:
    parts = []
    for c in calls:
        if c.name == "get_macro":
            cur = c.arguments.get("currency")
            parts.append(f"курс {cur}" if cur else "ключевую ставку")
        elif c.name in PLAN_LABELS:
            parts.append(PLAN_LABELS[c.name])
    return "Проверю: " + "; ".join(dict.fromkeys(parts)) if parts else "Собираю данные"


class AgentLoop:
    def __init__(self, ctx: AgentContext, candidates: list[ProductCandidate], weak_note: str | None):
        self.ctx = ctx
        self.candidates = candidates
        role_name, role_focus = ROLE_TEXT[ctx.role]
        rendered = ctx.app.prompts.render(
            "agent",
            role_name=role_name,
            role_focus=role_focus,
            profile_brief=profile_brief(ctx.app.prompts, ctx.app.taxonomy, ctx.profile),
            evidence_block=evidence_block(ctx.evidence.all(), KIND_LABELS),
            chain_block=chain_block(ctx.exposure.paths if ctx.exposure else [], ctx.path_eids),
            products_block=products_block(candidates),
            max_tool_calls=ctx.limits.max_tool_calls,
            weak_note=weak_note,
        )
        self.version = rendered.version
        self.messages: list[Message] = list(rendered.messages)
        self.specs = tool_specs(AGENT_TOOLS)
        self.model = ""
        self.family = ""
        self.round = 0

    async def _call(self, *, forced: bool = False) -> LLMResult:
        ctx = self.ctx
        req = LLMRequest(
            task="agent", messages=self.messages, prompt_version=self.version,
            tools=[s for s in self.specs if s.name == "submit_insight"] if forced else self.specs,
            tool_choice={"type": "function", "function": {"name": "submit_insight"}} if forced else "auto",
            priority=ctx.priority, run_id=ctx.run_id,
        )  # fmt: skip
        res = await ctx.app.router.complete(req)
        self.model, self.family = res.model_key, res.family
        return res

    async def _round(self, *, forced: bool = False) -> InsightDraft | None:
        """Один вызов модели; инструменты выполняются, черновик — если пришёл валидный submit_insight."""
        ctx = self.ctx
        self.round += 1
        res = await self._call(forced=forced)
        calls = res.tool_calls
        text = (res.content or "").strip()
        if text:
            kind = "plan" if self.round == 1 else "thought"
            ctx.trace.emit(kind, "tools", "План" if kind == "plan" else "Промежуточный вывод",
                           payload={"text": text[:THOUGHT_CHARS]})  # fmt: skip
        elif self.round == 1 and calls:
            plan = _plan_from_calls(calls)
            ctx.trace.emit("plan", "tools", "План", payload={"text": plan})
        if not calls:
            self.messages += [
                Message(role="assistant", content=text or None),
                Message(role="user", content=NUDGE),
            ]
            return None
        self.messages.append(Message(role="assistant", content=text or None, tool_calls=calls))
        results = await asyncio.gather(*(execute_tool_call(ctx, c) for c in calls))
        draft: InsightDraft | None = None
        for call, result in zip(calls, results, strict=True):
            if call.name == "submit_insight" and result.ok and draft is None:
                draft = InsightDraft.model_validate(result.data["draft"])
                content = json.dumps(
                    {"ok": True, "summary": "Черновик принят на проверку"}, ensure_ascii=False
                )
            else:
                content = result_for_model(result)
            self.messages.append(Message(role="tool", tool_call_id=call.id, content=content))
        return draft

    async def run_rounds(self, max_rounds: int) -> InsightDraft:
        draft = None
        for _ in range(max_rounds):
            try:
                draft = await self._round()
            except BudgetExceeded as exc:
                if exc.scope != "run":
                    raise
                self.ctx.trace.emit("budget.warning", "tools", "Режим экономии бюджета: завершаю разбор",
                                    status="warn", payload={"mode": "force_submit", "spent_rub": self.ctx.cost_rub})  # fmt: skip
                break
            if draft is not None:
                return draft
        draft = await self._round(forced=True)
        if draft is None:
            raise LLMInvalidOutput("Модель не передала черновик", {"task": "agent"})
        return draft

    async def revise(self, report: VerificationReport) -> InsightDraft:
        rev = self.ctx.app.prompts.render(
            "revise", role_name=ROLE_TEXT[self.ctx.role][0], role_focus=ROLE_TEXT[self.ctx.role][1],
            issues=report.issues, draft_json="(см. последний вызов submit_insight выше)",
        )  # fmt: skip
        self.messages.append(rev.messages[-1])
        return await self.run_rounds(1)  # один раунд инструментов, затем принудительный submit


async def run_agentic(ctx: AgentContext, *, weak_note: str | None = None) -> Insight:
    event = await collect_base(ctx, plan_text="Агентный режим: модель сама выбирает инструменты")
    candidates = ctx.app.products.match(ctx.exposure, ctx.profile, ctx.role) if ctx.exposure else []
    if not tools_supported(ctx):
        ctx.trace.emit("plan", "plan", "Модели без поддержки инструментов — перехожу в пакетный режим",
                       status="warn", payload={"text": "fallback: pipeline"})  # fmt: skip
        return await draft_and_verify(ctx, candidates, event=event)
    ctx.tool_calls = 0  # предзагрузка не входит в лимит модели
    loop = AgentLoop(ctx, candidates, weak_note)
    ctx.trace.phase("tools", "Исследую тему")
    draft = await loop.run_rounds(ctx.limits.max_tool_rounds)
    ctx.trace.emit("draft.ready", "draft", f"Черновик готов, утверждений: {len(draft.claims())}",
                   payload={"headline": draft.headline, "claims": len(draft.claims())})  # fmt: skip

    inp = inputs_from_context(ctx, candidates, expected_impact(ctx))
    exclude = [loop.family] if loop.family else []
    ctx.trace.phase("verify", "Проверяю факты")
    draft, report = await verify(ctx, draft, inp, attempt=1, exclude_families=exclude)
    attempts = 1
    while not report.passed and attempts <= ctx.limits.max_revisions:
        ctx.trace.phase("revise", "Дорабатываю")
        ctx.trace.emit("revise.started", "revise", f"Дорабатываю: замечаний {len(report.issues)}",
                       payload={"issues": report.issues[:10]})  # fmt: skip
        draft = await loop.revise(report)
        attempts += 1
        ctx.trace.phase("verify", "Проверяю исправления")
        draft, report = await verify(ctx, draft, inp, attempt=attempts, exclude_families=exclude)
    return finish(
        ctx,
        draft,
        report,
        attempts=attempts,
        model=loop.model or "agent",
        prompt_version=agent_prompt_version(ctx),
    )
