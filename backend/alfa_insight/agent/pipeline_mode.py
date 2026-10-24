"""Режим pipeline: фиксированный план, черновик, проверка, доработка, финализация (docs/08-agent.md §6)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.finalize import FinalizeInput, finalize
from alfa_insight.agent.render import chain_block, profile_brief
from alfa_insight.agent.schemas import Insight, InsightDraft, VerificationReport
from alfa_insight.agent.tools import ToolResult, execute_tool_call
from alfa_insight.agent.verifier import degrade, inputs_from_context, verify
from alfa_insight.errors import AppError
from alfa_insight.llm.types import Message, ToolCall
from alfa_insight.products.catalog import ProductCandidate, products_block
from alfa_insight.ranking.models import ImpactLevel
from alfa_insight.store.events import EventStore
from alfa_insight.store.rankings import RankingStore

ROLE_TEXT = {
    "cfo": ("финансовый директор", "себестоимость, маржа, налоги, бюджет, финансирование"),
    "treasurer": ("казначей", "ликвидность, валютный и процентный риск, платежи, долговая нагрузка"),
    "owner": ("собственник бизнеса", "стратегия, рынок и спрос, регулирование, крупные решения"),
}
RATE_FACTORS = {"key_rate", "credit_conditions"}
MAX_FX = 2
PIPELINE_STEPS = [
    {"tool": "get_event", "why": "материалы события"},
    {"tool": "get_company_profile", "why": "профиль и признаки компании"},
    {"tool": "compute_exposure", "why": "пути влияния на компанию"},
    {"tool": "search_alfa_research", "why": "позиция аналитиков банка"},
    {"tool": "get_macro", "why": "ставка и курсы, если они в путях влияния"},
    {"tool": "get_counterparties", "why": "крупнейшие контрагенты главного пути"},
]


class RunFailed(AppError):
    """Прогон нельзя продолжить; `code` — из docs/08-agent.md §17."""


def insight_prompt_version(ctx: AgentContext) -> str:
    p = ctx.app.prompts
    return f"{p.version('draft')}+{p.version('verify')}"


async def _tool(ctx: AgentContext, name: str, **args: Any) -> ToolResult:
    ctx_id = f"pl_{name}_{ctx.tool_calls + 1}"
    return await execute_tool_call(ctx, ToolCall(id=ctx_id, name=name, arguments=args))


async def collect_base(
    ctx: AgentContext, *, plan_text: str = "Пакетный режим: фиксированный план"
) -> dict[str, Any]:
    """Шаги 1–3 §6 (общие для обоих режимов): событие, профиль, пути влияния."""
    assert ctx.event_id is not None
    ctx.trace.phase("plan", "План")
    ctx.trace.emit("plan", "plan", plan_text, payload={"text": plan_text, "steps": PIPELINE_STEPS[:3]})
    ctx.trace.phase("tools", "Сбор данных")
    ev = await _tool(ctx, "get_event", event_id=ctx.event_id)
    if not ev.ok:
        raise RunFailed(ev.error or "Событие недоступно", code="internal")
    await _tool(ctx, "get_company_profile")
    await _tool(ctx, "compute_exposure", event_id=ctx.event_id)
    return ev.data


async def collect_rest(ctx: AgentContext, event: dict[str, Any]) -> None:
    """Шаги 4–7 §6 параллельно: аналитика банка, ставка и курсы из путей, контрагенты главного пути."""
    paths = ctx.exposure.paths if ctx.exposure else []
    top = paths[:3]
    industries = list(dict.fromkeys(p.industry_id for p in top if p.industry_id))
    factors = list(dict.fromkeys(p.factor_id for p in top if p.factor_id))
    names = [p.industry_name or p.factor_name or "" for p in top]
    query = " ".join([event.get("title", ""), event.get("summary", ""), *names])[:200]
    jobs = [
        _tool(ctx, "search_alfa_research", query=query, industry_ids=industries, factor_ids=factors, limit=4)
    ]
    event_factors = {f["factor_id"] for f in event.get("factors", [])}
    path_factors = {p.factor_id for p in paths if p.factor_id}
    if (path_factors | event_factors) & RATE_FACTORS:
        jobs.append(_tool(ctx, "get_macro", indicator="key_rate"))
    fx = [
        f.removeprefix("fx_").upper()
        for f in dict.fromkeys(p.factor_id for p in paths if p.factor_id)
        if f.startswith("fx_")
    ]
    for cur in fx[:MAX_FX]:
        jobs.append(_tool(ctx, "get_macro", indicator="fx", currency=cur))
    if paths and paths[0].channel in ("supply", "demand") and paths[0].industry_id:
        direction = "suppliers" if paths[0].channel == "supply" else "buyers"
        jobs.append(
            _tool(ctx, "get_counterparties", direction=direction, industry_id=paths[0].industry_id, limit=3)
        )
    await asyncio.gather(*jobs)
    ctx.trace.emit("phase.completed", "tools", "Данные собраны", payload={"evidence": len(ctx.evidence)})


def expected_impact(ctx: AgentContext) -> ImpactLevel | None:
    assert ctx.event_id is not None
    row = RankingStore(ctx.app.db).get(ctx.company_id, ctx.event_id, ctx.role)
    if row is not None:
        return row["impact_level"]  # type: ignore[no-any-return]
    signals = EventStore(ctx.app.db).load_signals([ctx.event_id])
    if not signals:
        return None
    return ctx.app.ranking.rank_one(signals[0], ctx.profile, ctx.role).impact_level


def draft_messages(ctx: AgentContext, candidates: list[ProductCandidate]) -> tuple[list[Message], str]:
    role_name, role_focus = ROLE_TEXT[ctx.role]
    reg = ctx.evidence
    evidence = [
        {
            "eid": e.eid, "kind": e.kind, "kind_label": reg.kind_label(e), "title": e.title,
            "publisher": e.publisher, "published_at": e.published_at.date().isoformat() if e.published_at else None,
            "untrusted": e.untrusted, "text": e.text,
        }
        for e in reg.all()
    ]  # fmt: skip
    rendered = ctx.app.prompts.render(
        "draft",
        role_name=role_name,
        role_focus=role_focus,
        profile_brief=profile_brief(ctx.app.prompts, ctx.app.taxonomy, ctx.profile),
        evidence=evidence,
        chain_block=chain_block(ctx.exposure.paths if ctx.exposure else [], ctx.path_eids),
        products_block=products_block(candidates),
    )
    return rendered.messages, rendered.version


async def run_pipeline(ctx: AgentContext) -> Insight:
    event = await collect_base(ctx)
    candidates = ctx.app.products.match(ctx.exposure, ctx.profile, ctx.role) if ctx.exposure else []
    return await draft_and_verify(ctx, candidates, event=event)


async def draft_and_verify(
    ctx: AgentContext, candidates: list[ProductCandidate], *, event: dict[str, Any] | None = None
) -> Insight:
    """Шаги 4–7 (если передано событие), черновик, проверка, доработка, финализация."""
    if event is not None:
        await collect_rest(ctx, event)
    ctx.trace.phase("draft", "Пишу разбор")
    messages, version = draft_messages(ctx, candidates)
    res = await ctx.app.router.structured(
        task="draft", messages=messages, schema=InsightDraft, prompt_version=version,
        priority=ctx.priority, run_id=ctx.run_id,
    )  # fmt: skip
    draft = res.value
    model = res.raw.model_key
    ctx.trace.emit("draft.ready", "draft", f"Черновик готов, утверждений: {len(draft.claims())}",
                   payload={"headline": draft.headline, "claims": len(draft.claims())})  # fmt: skip

    inp = inputs_from_context(ctx, candidates, expected_impact(ctx))
    exclude = [res.raw.family]  # судья — модель другого семейства, чем у черновика
    ctx.trace.phase("verify", "Проверяю факты")
    draft, report = await verify(ctx, draft, inp, attempt=1, exclude_families=exclude)
    attempts = 1
    while not report.passed and attempts <= ctx.limits.max_revisions:
        ctx.trace.phase("revise", "Дорабатываю")
        ctx.trace.emit("revise.started", "revise", f"Дорабатываю: замечаний {len(report.issues)}",
                       payload={"issues": report.issues[:10]})  # fmt: skip
        draft, model = await _revise(ctx, messages, draft, report)
        attempts += 1
        ctx.trace.phase("verify", "Проверяю исправления")
        draft, report = await verify(ctx, draft, inp, attempt=attempts, exclude_families=exclude)
    return finish(
        ctx, draft, report, attempts=attempts, model=model, prompt_version=insight_prompt_version(ctx)
    )


def finish(
    ctx: AgentContext,
    draft: InsightDraft,
    report: VerificationReport,
    *,
    attempts: int,
    model: str,
    prompt_version: str,
) -> Insight:
    """Деградация при непройденной проверке и финализация (§9.5, §10)."""
    ctx.trace.phase("finalize", "Оформляю результат")
    if report.passed:
        status, removed, share, warnings = "published", 0, report.supported_share, []
    else:
        dg = degrade(draft, report)
        draft, status, removed, share, warnings = (
            dg.draft,
            dg.status,
            dg.removed_claims,
            dg.supported_share,
            dg.warnings,
        )
    warnings = [*warnings, *(c.message for c in report.checks if c.status == "warn")][:8]
    return finalize(
        ctx,
        FinalizeInput(
            draft=draft, report=report, status=status, removed_claims=removed, supported_share=share,  # type: ignore[arg-type]
            warnings=warnings, attempts=attempts, model=model, prompt_version=prompt_version,
        ),
    )  # fmt: skip


async def _revise(
    ctx: AgentContext, draft_msgs: list[Message], draft: InsightDraft, report: VerificationReport
) -> tuple[InsightDraft, str]:
    """system + draft.user + assistant(черновик) + revise.user (05-prompts.md §9)."""
    draft_json = json.dumps(draft.model_dump(mode="json"), ensure_ascii=False)
    rev = ctx.app.prompts.render(
        "revise", role_name=ROLE_TEXT[ctx.role][0], role_focus=ROLE_TEXT[ctx.role][1],
        issues=report.issues, draft_json=draft_json,
    )  # fmt: skip
    messages = [*draft_msgs, Message(role="assistant", content=draft_json), rev.messages[-1]]
    res = await ctx.app.router.structured(
        task="revise", messages=messages, schema=InsightDraft, prompt_version=rev.version,
        priority=ctx.priority, run_id=ctx.run_id,
    )  # fmt: skip
    return res.value, res.raw.model_key
