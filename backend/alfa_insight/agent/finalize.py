"""Финализация: ссылки → источники, граф, продукты, уверенность, запись инсайта (docs/08-agent.md §10)."""

from __future__ import annotations

from dataclasses import dataclass

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.evidence import EvidenceItem
from alfa_insight.agent.schemas import (
    Claim,
    ConfidenceInfo,
    EventBrief,
    Insight,
    InsightDraft,
    InsightStatus,
    Level,
    ProductOffer,
    SourceRef,
    VerificationReport,
    VerificationSummary,
)
from alfa_insight.data.profiles import pct
from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.ids import new_id
from alfa_insight.ranking.chain import build_graph, chain_preview
from alfa_insight.store.events import EventRow, EventStore
from alfa_insight.store.insights import EXCERPT_CHARS, InsightStore, SourceIn
from alfa_insight.store.news import NewsStore
from alfa_insight.store.runs import RunStore
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

HIGH, MEDIUM = 0.75, 0.5


@dataclass
class FinalizeInput:
    draft: InsightDraft  # после автоисправлений и деградации, refs — E-id
    report: VerificationReport
    status: InsightStatus
    removed_claims: int
    supported_share: float
    warnings: list[str]
    attempts: int
    model: str
    prompt_version: str


def event_publishers(db: SqliteDB, event_id: int) -> list[str]:
    news = NewsStore(db)
    out: list[str] = []
    for nid in EventStore(db).news_ids(event_id):
        row = news.get(nid)
        if row is not None and row.origin != "user" and row.publisher not in out:
            out.append(row.publisher)
    return out


def event_brief(ev: EventRow, publishers: list[str]) -> EventBrief:
    return EventBrief(
        id=ev.id, title=ev.title, summary=ev.summary, event_type=ev.event_type, importance=ev.importance,
        first_seen_at=parse_dt(ev.first_seen_at), last_seen_at=parse_dt(ev.last_seen_at), publishers=publishers,
        news_count=ev.news_count, visibility=ev.visibility, injection_suspected=ev.injection_suspected,  # type: ignore[arg-type]
    )  # fmt: skip


def confidence(
    ctx: AgentContext, ev: EventRow, share: float, status: InsightStatus, *, llm_skipped: bool, graded: int
) -> ConfidenceInfo:
    """§10 п. 4: 0.35·v + 0.20·p + 0.15·t + 0.15·k + 0.15·g; needs_review — не выше low."""
    p = min(1.0, ev.publisher_count / 3)
    first = ctx.exposure.paths[0] if ctx.exposure and ctx.exposure.paths else None
    if first is not None and first.channel in ("supply", "demand"):
        k = ctx.profile.coverage.get(first.channel, 0.0)
    else:
        k = 1.0
    value = round(0.35 * share + 0.20 * p + 0.15 * ev.max_trust + 0.15 * k + 0.15 * ev.tag_confidence, 4)
    level: Level = "high" if value >= HIGH else "medium" if value >= MEDIUM else "low"
    if status == "needs_review":
        level = "low"
    reasons: list[str] = []
    if ev.publisher_count >= 2:
        reasons.append(
            f"{ev.publisher_count} независимых источника"
            if ev.publisher_count < 5
            else f"{ev.publisher_count} независимых источников"
        )
    elif ev.visibility == "private":
        reasons.append("один источник: текст, который вы прислали")
    else:
        reasons.append("пока один источник")
    if first is not None and first.channel in ("supply", "demand"):
        reasons.append(
            f"данные о платежах покрывают {pct(k)}"
            if k > 0
            else "долей по платежам нет, использованы типичные для отрасли"
        )
    if not llm_skipped and graded:
        reasons.append(f"проверка: {round(share * graded)} из {graded} утверждений подтверждены")
    if not any(e.kind == "alfa" for e in ctx.evidence.all()):
        reasons.append("у аналитиков банка нет материалов по теме")
    return ConfidenceInfo(value=value, level=level, reasons=reasons[:4])


def _map_refs(claim: Claim, ctx: AgentContext, used: dict[str, EvidenceItem]) -> None:
    ids = []
    for ref in claim.refs:
        item = ctx.evidence.get(ref)
        if item is None:
            continue
        used[item.source_id] = item
        if item.source_id not in ids:
            ids.append(item.source_id)
    claim.refs = ids


def _source_in(item: EvidenceItem, company_id: str) -> SourceIn:
    private = item.kind in ("client_data", "user_input")
    return SourceIn(
        id=item.source_id, kind=item.kind, title=item.title, company_id=company_id if private else None,
        publisher=item.publisher, url=item.url, published_at=to_iso(item.published_at) if item.published_at else None,
        excerpt=(item.full_text or item.text)[:EXCERPT_CHARS],
        payload={k: v for k, v in item.meta.items() if k != "full_text"},
    )  # fmt: skip


def finalize(ctx: AgentContext, inp: FinalizeInput) -> Insight:
    app = ctx.app
    assert ctx.event_id is not None
    ev = EventStore(app.db).get(ctx.event_id)
    if ev is None:
        raise ValueError(f"событие {ctx.event_id} не найдено")
    draft = inp.draft.model_copy(deep=True)
    used: dict[str, EvidenceItem] = {}
    for _, c in draft.claims():
        _map_refs(c, ctx, used)

    # граф: источники узлов — evidence путей и новости события
    event_news = [
        e.source_id
        for e in ctx.evidence.all()
        if e.meta.get("event_id") == ev.id and e.kind in ("news", "user_input")
    ]
    path_sources: dict[str, list[str]] = {}
    graph_items: dict[str, EvidenceItem] = {}
    exposure = ctx.exposure
    if exposure is not None:
        for pid, eid in ctx.path_eids.items():
            item = ctx.evidence.get(eid)
            if item is not None:
                path_sources[pid] = [item.source_id, *event_news[:2]]
                graph_items[item.source_id] = item
        chain = build_graph(ev.title, exposure, app.taxonomy, path_sources=path_sources)
        preview = chain_preview(ev.title, exposure, app.taxonomy)
    else:
        from alfa_insight.ranking.models import ChainGraph

        chain, preview = ChainGraph(nodes=[], edges=[]), None
    for sid in event_news[:2]:
        item = ctx.evidence.by_source(sid)
        if item is not None:
            graph_items[sid] = item

    offers: list[ProductOffer] = []
    for i, a in enumerate(draft.actions):
        prod = app.products.get(a.product_id) if a.product_id else None
        if prod is None:
            a.product_id = None
            continue
        offers.append(
            ProductOffer(product_id=prod.id, name=prod.name, pitch=prod.pitch, url=prod.url, action_index=i)
        )

    graded = sum(1 for _, c in draft.claims() if c.type in ("fact", "bank"))
    conf = confidence(
        ctx, ev, inp.supported_share, inp.status, llm_skipped=inp.report.llm_skipped, graded=graded
    )
    sources = [
        SourceRef(
            id=i.source_id,
            kind=i.kind,
            title=i.title,
            publisher=i.publisher,
            url=i.url,
            published_at=i.published_at,
        )
        for i in used.values()
    ]
    runs = RunStore(app.db)
    run = runs.get(ctx.run_id)
    cost = run.cost_rub if run else ctx.cost_rub
    insight = Insight(
        **draft.model_dump(),
        id=new_id("ins"),
        company_id=ctx.company_id,
        status=inp.status,
        event=event_brief(ev, event_publishers(app.db, ev.id)),
        chain=chain,
        chain_preview=preview,
        sources=sources,
        products=offers,
        confidence=conf,
        verification=VerificationSummary(
            passed=inp.report.passed,
            supported_share=inp.supported_share,
            attempts=inp.attempts,
            removed_claims=inp.removed_claims,
            warnings=inp.warnings,
            llm_skipped=inp.report.llm_skipped,
        ),
        role_generated_for=ctx.role,
        prompt_version=inp.prompt_version,
        profile_version=ctx.profile.profile_version,
        model=inp.model,
        trace_id=ctx.run_id,
        cost_rub=round(cost, 4),
        created_at=utc_now(),
    )
    store = InsightStore(app.db)
    all_items = {**graph_items, **used}
    store.upsert_sources(_source_in(i, ctx.company_id) for i in all_items.values())
    store.save(
        insight=insight.model_dump(mode="json"), verification=inp.report.model_dump(mode="json"), run_id=ctx.run_id,
        event_id=ev.id, confidence=conf.value, confidence_level=conf.level, source_ids=list(all_items),
    )  # fmt: skip
    return insight
