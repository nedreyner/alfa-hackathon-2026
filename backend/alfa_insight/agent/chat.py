"""Чат по инсайту: вопросы клиента с опорой на источники (docs/08-agent.md §13)."""

from __future__ import annotations

import time
from typing import Any

from alfa_insight.agent.agentic_mode import AgentLoop
from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.evidence import KIND_LABELS, EvidenceItem
from alfa_insight.agent.render import evidence_block, profile_brief
from alfa_insight.agent.schemas import ChatAnswer, Claim, Insight
from alfa_insight.agent.verifier import _domain, attach_number_refs, claim_problems
from alfa_insight.errors import NotFoundError
from alfa_insight.llm.prompts import sanitize_untrusted
from alfa_insight.llm.types import Message
from alfa_insight.store.chat import ChatStore
from alfa_insight.store.insights import EXCERPT_CHARS, InsightStore, SourceIn
from alfa_insight.store.news import NewsStore
from alfa_insight.store.research import ResearchStore
from alfa_insight.store.runs import RunStore

CHAT_TOOLS = [
    "open_evidence", "search_news", "search_alfa_research", "get_macro", "get_counterparties",
    "compute_exposure", "submit_answer",
]  # fmt: skip
CHAT_ROUNDS = 3
HISTORY = 6
QUESTION_CHARS = 1000
FALLBACK = "Не могу ответить на это с опорой на источники"


def load_insight(ctx: AgentContext, insight_id: str) -> Insight:
    row = InsightStore(ctx.app.db).get(insight_id)
    if row is None or row.company_id != ctx.company_id:
        raise NotFoundError("Инсайт не найден", {"insight_id": insight_id})
    return Insight.model_validate(row.payload)


def _source_text(ctx: AgentContext, source_id: str, excerpt: str) -> str:
    """Полный текст источника из исходных таблиц; для данных клиента и ЦБ — сохранённый excerpt."""
    kind, _, rest = source_id.partition(":")
    if kind in ("news", "user") and rest.isdigit():
        row = NewsStore(ctx.app.db).get(int(rest))
        if row is not None:
            return f"{row.title}\n{row.body or row.rss_summary or ''}".strip()
    if kind == "alfa":
        chunk = ResearchStore(ctx.app.db).chunk_by_source(source_id)
        if chunk is not None:
            return str(chunk["text"])
    return excerpt


def restore_evidence(ctx: AgentContext, insight: Insight) -> None:
    """Реестр E1..En в порядке источников инсайта (§13 п. 1)."""
    store = InsightStore(ctx.app.db)
    for ref in insight.sources:
        src = store.source(ref.id, company_id=ctx.company_id)
        if src is None:
            continue
        ctx.evidence.add(
            source_id=src.id, kind=src.kind, title=src.title, publisher=src.publisher, url=src.url,  # type: ignore[arg-type]
            published_at=ref.published_at, text=_source_text(ctx, src.id, src.excerpt), meta=dict(src.payload),
        )  # fmt: skip


def _answer_text(content: dict[str, Any]) -> str:
    return " ".join(b["text"] for b in content.get("blocks", []))


def build_messages(
    ctx: AgentContext, insight: Insight, history: list[dict[str, Any]], question: str
) -> tuple[list[Message], str]:
    """system + user(контекст и первый вопрос окна) + история + текущий вопрос."""
    by_source = {e.source_id: e.eid for e in ctx.evidence.all()}
    claims = [
        {"type": c.type, "text": c.text, "evidence": [by_source[r] for r in c.refs if r in by_source]}
        for _, c in insight.claims()
    ]
    window = history[-HISTORY:]
    if window and window[0]["role"] == "assistant":
        window = window[1:]
    first_q = window[0]["content"]["text"] if window else question
    rendered = ctx.app.prompts.render(
        "chat",
        max_tool_calls=ctx.limits.max_tool_calls,
        profile_brief=profile_brief(ctx.app.prompts, ctx.app.taxonomy, ctx.profile),
        insight=insight,
        insight_claims=claims,
        evidence_block=evidence_block(ctx.evidence.all(), KIND_LABELS),
        question=sanitize_untrusted(first_q, QUESTION_CHARS),
    )
    messages = list(rendered.messages)
    for m in window[1:]:
        if m["role"] == "user":
            messages.append(
                Message(role="user", content=sanitize_untrusted(m["content"]["text"], QUESTION_CHARS))
            )
        else:
            messages.append(Message(role="assistant", content=_answer_text(m["content"])))
    if window:
        messages.append(Message(role="user", content=sanitize_untrusted(question, QUESTION_CHARS)))
    return messages, rendered.version


def check_answer(ctx: AgentContext, answer: ChatAnswer) -> tuple[ChatAnswer, int]:
    """§13 п. 4: блоки с fail по refs/источнику/числам/URL удаляются; все удалены — один блок ai."""
    domains = {d for d in (_domain(e.url) for e in ctx.evidence.all() if e.url) if d}
    for b in answer.blocks:
        if b.type in ("fact", "bank"):
            attach_number_refs(b, ctx.evidence)
    kept = [b for b in answer.blocks if not claim_problems(b, ctx.evidence, domains)]
    removed = len(answer.blocks) - len(kept)
    if not kept:
        kept = [Claim(text=FALLBACK, type="ai", refs=[], confidence="low")]
    return ChatAnswer(blocks=kept, followups=answer.followups), removed


async def run_chat(
    ctx: AgentContext, *, insight_id: str, thread_id: str, user_message_id: int
) -> dict[str, Any]:
    started = time.monotonic()
    insight = load_insight(ctx, insight_id)
    ctx.event_id = insight.event.id
    ctx.allowed_event_ids = {insight.event.id}
    chat = ChatStore(ctx.app.db)
    history = chat.thread(thread_id)
    current = next((m for m in history if m["id"] == user_message_id), None)
    if current is None:
        raise NotFoundError("Сообщение не найдено", {"message_id": user_message_id})
    question = current["content"]["text"]
    prior = [m for m in history if m["id"] < user_message_id]

    ctx.trace.phase("plan", "Готовлю ответ")
    restore_evidence(ctx, insight)
    messages, version = build_messages(ctx, insight, prior, question)
    loop = AgentLoop(
        ctx, messages, version, task="chat", tools=CHAT_TOOLS, terminal="submit_answer", schema=ChatAnswer
    )
    loop.current_event_only = True
    ctx.trace.phase("tools", "Ищу ответ")
    raw = await loop.run_rounds(CHAT_ROUNDS)
    assert isinstance(raw, ChatAnswer)
    ctx.trace.phase("verify", "Проверяю ответ")
    answer, removed = check_answer(ctx, raw)
    ctx.trace.emit("verify.report", "verify",
                   "Ответ проверен" + (f"; скрыто блоков без подтверждения: {removed}" if removed else ""),
                   status="warn" if removed else "ok", payload={"removed": removed, "blocks": len(answer.blocks)})  # fmt: skip

    ctx.trace.phase("finalize", "Сохраняю ответ")
    used: dict[str, EvidenceItem] = {}
    for b in answer.blocks:
        ids = []
        for ref in b.refs:
            item = ctx.evidence.get(ref)
            if item is not None:
                used[item.source_id] = item
                ids.append(item.source_id)
        b.refs = list(dict.fromkeys(ids))
    InsightStore(ctx.app.db).upsert_sources(
        SourceIn(
            id=i.source_id, kind=i.kind, title=i.title, publisher=i.publisher, url=i.url,
            company_id=ctx.company_id if i.kind in ("client_data", "user_input") else None,
            published_at=i.published_at.isoformat() if i.published_at else None,
            excerpt=(i.full_text or i.text)[:EXCERPT_CHARS], payload=dict(i.meta),
        )
        for i in used.values()
    )  # fmt: skip
    message_id = chat.add(
        thread_id=thread_id, insight_id=insight_id, company_id=ctx.company_id, session_id=current["session_id"],
        role="assistant", content=answer.model_dump(mode="json"), run_id=ctx.run_id,
    )  # fmt: skip
    duration = int((time.monotonic() - started) * 1000)
    run = RunStore(ctx.app.db).get(ctx.run_id)
    cost = round(run.cost_rub if run else ctx.cost_rub, 4)
    result = {"message_id": message_id, "thread_id": thread_id, "duration_ms": duration, "cost_rub": cost}
    ctx.trace.emit("run.completed", "finalize", f"Ответ готов за {max(1, round(duration / 1000))} с",
                   payload={"message_id": message_id, "duration_ms": duration, "cost_rub": cost})  # fmt: skip
    return result
