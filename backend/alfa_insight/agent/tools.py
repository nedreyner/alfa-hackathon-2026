"""Инструменты агента: реестр, выполнение вызова, формат результата (docs/08-agent.md §5).

Компания всегда берётся из `ctx.company_id` — в аргументах её нет (ADR-23).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from alfa_insight.agent.context import AgentContext
from alfa_insight.agent.evidence import EvidenceItem, EvidenceRegistry
from alfa_insight.agent.render import CHANNEL_RU, path_text, path_weight_label, profile_brief, untrusted_wrap
from alfa_insight.agent.schemas import ChatAnswer, InsightDraft
from alfa_insight.data.profiles import pct
from alfa_insight.llm.structured import to_llm_schema
from alfa_insight.llm.types import ToolCall, ToolSpec
from alfa_insight.ranking.chain import compute_exposure as chain_exposure
from alfa_insight.search.news import search_news as fts_news
from alfa_insight.search.research import search_research
from alfa_insight.store.events import EventStore
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.news import NewsStore
from alfa_insight.text.normalize import lower_name
from alfa_insight.timeutil import parse_dt

TOOL_TIMEOUT_S = 10.0
MAX_RESULT_CHARS = 6000
EVENT_NEWS_LIMIT = 5
PROFILE_TEXT_CHARS = 4000  # профиль со списком признаков не режем до общего лимита evidence
EXPOSURE_EVIDENCE_PATHS = 6
CURRENCIES = ("USD", "EUR", "CNY", "TRY", "AED", "INR", "KZT")
CURRENCY_RU = {
    "USD": "доллара",
    "EUR": "евро",
    "CNY": "юаня",
    "TRY": "лиры",
    "AED": "дирхама",
    "INR": "рупии",
    "KZT": "тенге",
}
INSIGHT_KINDS = frozenset({"insight", "analyze"})
CHAT_KINDS = frozenset({"chat"})
ALL_KINDS = INSIGHT_KINDS | CHAT_KINDS


class ToolFailure(Exception):
    """Ошибка, понятная модели: превращается в `ok=false` с этим текстом."""


class ToolResult(BaseModel):
    ok: bool
    summary: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# ── аргументы ──
class NoArgs(BaseModel):
    pass


class EventArgs(BaseModel):
    event_id: int = Field(description="id события")


class CounterpartiesArgs(BaseModel):
    direction: Literal["suppliers", "buyers"] = Field(
        description="suppliers — поставщики, buyers — покупатели"
    )
    industry_id: str | None = Field(default=None, description="Отрасль контрагентов (необязательно)")
    limit: int = Field(default=5, ge=1, le=10)


class SearchNewsArgs(BaseModel):
    query: str = Field(min_length=3, max_length=200, description="Поисковый запрос по-русски")
    days: int = Field(default=30, ge=1, le=180, description="Глубина поиска в днях")
    industry_ids: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=5, ge=1, le=8)


class SearchResearchArgs(BaseModel):
    query: str = Field(min_length=3, max_length=200, description="Тема по-русски")
    industry_ids: list[str] = Field(default_factory=list, max_length=5)
    factor_ids: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=4, ge=1, le=6)


class MacroArgs(BaseModel):
    indicator: Literal["key_rate", "fx"] = Field(description="key_rate — ключевая ставка, fx — курс валюты")
    currency: Literal["USD", "EUR", "CNY", "TRY", "AED", "INR", "KZT"] | None = Field(
        default=None, description="Обязательно для fx"
    )
    days: int = Field(default=90, ge=7, le=365)


class OpenEvidenceArgs(BaseModel):
    eid: str = Field(pattern=r"^E\d{1,3}$", description="Идентификатор evidence, например E3")


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[AgentContext, Any], ToolResult]
    title: Callable[[Any], str]
    kinds: frozenset[str] = ALL_KINDS
    terminal: bool = False


TOOLS: dict[str, Tool] = {}


def tool(
    name: str,
    description: str,
    args_model: type[BaseModel],
    title: str | Callable[[Any], str],
    *,
    kinds: frozenset[str] = ALL_KINDS,
    terminal: bool = False,
) -> Callable[[Callable[[AgentContext, Any], ToolResult]], Callable[[AgentContext, Any], ToolResult]]:
    def deco(fn: Callable[[AgentContext, Any], ToolResult]) -> Callable[[AgentContext, Any], ToolResult]:
        TOOLS[name] = Tool(
            name=name,
            description=description,
            args_model=args_model,
            run=fn,
            title=title if callable(title) else (lambda _a, t=title: t),  # type: ignore[misc]
            kinds=kinds,
            terminal=terminal,
        )
        return fn

    return deco


def _add(ctx: AgentContext, out: list[EvidenceItem], **kw: Any) -> EvidenceItem | None:
    item = ctx.evidence.try_add(**kw)
    if item is not None and item not in out:
        out.append(item)
    return item


def _dt(value: str | None) -> datetime | None:
    return parse_dt(value) if value else None


def _news_text(title: str, body: str | None) -> str:
    body = (body or "").strip()
    return body if body.startswith(title) else f"{title}\n{body}".strip()


def _day(value: datetime | None) -> str:
    return value.strftime("%d.%m") if value else ""


# ── инструменты ──
@tool(
    "get_event",
    "Событие: заголовок, краткое содержание, тип, важность, издания, отраслевые теги и до 5 новостей с текстом.",
    EventArgs,
    "Читаю материалы события",
)
def get_event(ctx: AgentContext, args: EventArgs) -> ToolResult:
    events, news = EventStore(ctx.app.db), NewsStore(ctx.app.db)
    ev = events.get(args.event_id)
    if ev is None or (ev.visibility == "private" and ev.owner_company_id != ctx.company_id):
        raise ToolFailure(f"Событие {args.event_id} недоступно в этом разборе")
    [sig] = events.load_signals([ev.id])
    out: list[EvidenceItem] = []
    publishers: list[str] = []
    rows = [r for r in (news.get(nid) for nid in events.news_ids(ev.id)) if r is not None]
    rows.sort(key=lambda r: (r.id != ev.lead_news_id, -r.trust, r.published_at))
    for row in rows[:EVENT_NEWS_LIMIT]:
        user = row.origin == "user"
        _add(
            ctx, out,
            source_id=f"user:{row.id}" if user else f"news:{row.id}",
            kind="user_input" if user else "news",
            title=row.title, text=_news_text(row.title, row.body or row.rss_summary),
            publisher=None if user else row.publisher, url=row.url, published_at=_dt(row.published_at),
            meta={"news_id": row.id, "event_id": ev.id},
        )  # fmt: skip
    for row in rows:
        if row.origin != "user" and row.publisher not in publishers:
            publishers.append(row.publisher)
    tax = ctx.app.taxonomy
    industries = [
        {
            "industry_id": i.industry_id,
            "name": tax.industry(i.industry_id).name,
            "effect": i.effect,
            "impact": i.impact,
        }
        for i in sig.industries
    ]
    factors = [
        {
            "factor_id": f.factor_id,
            "name": tax.factor(f.factor_id).name,
            "direction": f.direction,
            "impact": f.impact,
        }
        for f in sig.factors
    ]
    pubs = ", ".join(publishers[:4]) or "текст пользователя"
    return ToolResult(
        ok=True,
        summary=f"«{ev.title}»: публикаций {ev.news_count} ({pubs}), важность {ev.importance} из 5",
        evidence=out,
        data={
            "event_id": ev.id, "title": ev.title, "summary": ev.summary, "event_type": ev.event_type,
            "importance": ev.importance, "horizon": ev.horizon, "publishers": publishers,
            "news_count": ev.news_count, "industries": industries, "factors": factors,
            "injection_suspected": ev.injection_suspected,
        },
    )  # fmt: skip


@tool(
    "get_company_profile",
    "Краткий профиль компании клиента: отрасль, продукты в банке, ВЭД, структура закупок и продаж, чувствительность к факторам, список признаков.",
    NoArgs,
    "Смотрю профиль компании",
)
def get_company_profile(ctx: AgentContext, args: NoArgs) -> ToolResult:
    p = ctx.profile
    text = profile_brief(ctx.app.prompts, ctx.app.taxonomy, p)
    out: list[EvidenceItem] = []
    _add(
        ctx, out, source_id=f"data:{p.company_id}:profile", kind="client_data",
        title="Профиль компании", text=text, meta={"profile_version": p.profile_version},
        text_chars=PROFILE_TEXT_CHARS,
    )  # fmt: skip
    return ToolResult(
        ok=True,
        summary=f"{p.industry_name}; признаков: {len(p.features)}; факторов чувствительности: {len(p.factor_exposure)}",
        evidence=out,
        data={"features": sorted(p.feature_keys())},
    )


@tool(
    "compute_exposure",
    "Пути влияния события на компанию (цепная реакция через отрасль, поставщиков, покупателей и макрофакторы) с долями и крупнейшими контрагентами.",
    EventArgs,
    "Считаю цепную реакцию",
)
def compute_exposure(ctx: AgentContext, args: EventArgs) -> ToolResult:
    signals = EventStore(ctx.app.db).load_signals([args.event_id])
    if not signals:
        raise ToolFailure(f"Событие {args.event_id} недоступно в этом разборе")
    sig = signals[0]
    exp = chain_exposure(
        sig, ctx.profile, ctx.role, ctx.app.ranking_config, ctx.app.taxonomy, ctx.app.counterparties
    )
    out: list[EvidenceItem] = []
    path_eids: dict[str, str] = {}
    for p in exp.paths[:EXPOSURE_EVIDENCE_PATHS]:
        key = f"{p.channel}.{p.factor_id if p.channel == 'factor' else p.industry_id}"
        label = p.factor_name if p.channel == "factor" else p.industry_name
        item = _add(
            ctx, out, source_id=f"data:{ctx.company_id}:exposure:{sig.event_id}:{key}", kind="client_data",
            title=f"Путь влияния: {CHANNEL_RU[p.channel]} — {lower_name(label)}", text=path_text(p),
            meta={"path_id": p.id, "path_key": key, "channel": p.channel, "event_id": sig.event_id},
        )  # fmt: skip
        if item is not None:
            path_eids[p.id] = item.eid
    if args.event_id == ctx.event_id:
        ctx.exposure, ctx.path_eids = exp, path_eids
    if not exp.paths:
        summary = "Путей влияния не найдено: событие слабо связано с данными компании"
    else:
        first = exp.paths[0]
        name = (first.factor_name if first.channel == "factor" else first.industry_name) or ""
        summary = (
            f"Путей влияния: {len(exp.paths)}; главный — {CHANNEL_RU[first.channel]}, {lower_name(name)}: "
            f"{path_weight_label(first)}"
        )
    return ToolResult(
        ok=True,
        summary=summary,
        evidence=out,
        data={
            "relevance": exp.relevance,
            "direction": exp.direction,
            "paths": [
                {"id": p.id, "eid": path_eids.get(p.id), "channel": p.channel, "contribution": p.contribution,
                 "direction": p.direction, "industry_id": p.industry_id, "factor_id": p.factor_id}
                for p in exp.paths[:EXPOSURE_EVIDENCE_PATHS]
            ],
        },
    )  # fmt: skip


@tool(
    "get_counterparties",
    "Крупнейшие поставщики или покупатели компании по платежам и их доли, при необходимости — только из одной отрасли.",
    CounterpartiesArgs,
    "Смотрю ключевых контрагентов",
)
def get_counterparties(ctx: AgentContext, args: CounterpartiesArgs) -> ToolResult:
    side = "supply" if args.direction == "suppliers" else "demand"
    items = ctx.app.counterparties.top(
        ctx.company_id, args.direction, industry_id=args.industry_id, limit=args.limit
    )
    what = "закупках" if side == "supply" else "продажах"
    who = "Поставщики" if side == "supply" else "Покупатели"
    scope = (
        lower_name(ctx.app.taxonomy.industry(args.industry_id).name) if args.industry_id else "все отрасли"
    )
    out: list[EvidenceItem] = []
    if not items:
        return ToolResult(ok=True, summary=f"{who}: данных о платежах нет ({scope})")
    lines = [
        f"{n}. {c.name} ({lower_name(c.industry_name)}) — {pct(c.share)} в {what}"
        for n, c in enumerate(items, 1)
    ]
    mix = ctx.profile.suppliers_mix if side == "supply" else ctx.profile.buyers_mix
    head = f"{who} компании, {scope}."
    if args.industry_id:
        share = next((s for s in mix if s.industry_id == args.industry_id), None)
        if share is not None:
            head += f" Доля отрасли в {what}: {pct(share.share_total)}."
    _add(
        ctx, out, source_id=f"data:{ctx.company_id}:{side}:{args.industry_id or 'all'}", kind="client_data",
        title=f"{who}: {scope}", text=head + "\n" + "\n".join(lines),
        meta={"direction": side, "industry_id": args.industry_id},
    )  # fmt: skip
    top = items[0]
    return ToolResult(
        ok=True,
        summary=f"{who} ({scope}): {len(items)}, крупнейший — {top.name}, {pct(top.share)}",
        evidence=out,
        data={
            "counterparties": [
                {"name": c.name, "industry_id": c.industry_id, "share": round(c.share, 4)} for c in items
            ]
        },
    )


@tool(
    "search_news",
    "Поиск связанных новостей за последние дни (полнотекстовый, по-русски). Найденные события становятся доступны для get_event и compute_exposure.",
    SearchNewsArgs,
    lambda a: f"Ищу связанные новости: «{a.query}»",
)
def search_news(ctx: AgentContext, args: SearchNewsArgs) -> ToolResult:
    hits = fts_news(
        ctx.app.db, args.query, company_id=ctx.company_id, days=args.days,
        industry_ids=args.industry_ids or None, limit=args.limit,
    )  # fmt: skip
    news = NewsStore(ctx.app.db)
    out: list[EvidenceItem] = []
    results: list[dict[str, Any]] = []
    for h in hits:
        row = news.get(h.news_id)
        if row is None:
            continue
        user = row.origin == "user"
        item = _add(
            ctx, out,
            source_id=f"user:{row.id}" if user else f"news:{row.id}", kind="user_input" if user else "news",
            title=row.title, text=_news_text(row.title, row.body or row.rss_summary or h.snippet),
            publisher=None if user else row.publisher, url=row.url, published_at=h.published_at,
            meta={"news_id": row.id, "event_id": h.event_id},
        )  # fmt: skip
        if h.event_id is not None:
            ctx.allowed_event_ids.add(h.event_id)
        results.append({"eid": item.eid if item else None, "event_id": h.event_id, "title": h.title})
    if not results:
        return ToolResult(ok=True, summary=f"По запросу «{args.query}» новостей не найдено")
    titles = "; ".join(f"«{str(r['title'])[:60]}»" for r in results[:3])
    return ToolResult(
        ok=True,
        summary=f"Найдено новостей: {len(results)} — {titles}",
        evidence=out,
        data={"results": results},
    )


@tool(
    "search_alfa_research",
    "Поиск по аналитическим обзорам Альфа-Банка: позиции, прогнозы и оценки аналитиков банка по теме.",
    SearchResearchArgs,
    "Ищу позицию аналитиков Альфа-Банка",
)
def search_alfa_research(ctx: AgentContext, args: SearchResearchArgs) -> ToolResult:
    hits = search_research(
        ctx.app.db, args.query, industry_ids=args.industry_ids, factor_ids=args.factor_ids, limit=args.limit
    )
    out: list[EvidenceItem] = []
    for h in hits:
        statements = "\n".join(f"— {i.statement}" for i in h.items[:3])
        text = (
            (f"{h.heading}\n" if h.heading else "")
            + h.text
            + (f"\nКлючевые тезисы:\n{statements}" if statements else "")
        )
        _add(
            ctx, out, source_id=h.source_id, kind="alfa", title=f"{h.doc_title}, с. {h.page}",
            text=text, publisher="Альфа-Банк",
            published_at=datetime(h.doc_date.year, h.doc_date.month, h.doc_date.day, tzinfo=UTC) if h.doc_date else None,
            meta={"doc_title": h.doc_title, "page": h.page, "heading": h.heading},
        )  # fmt: skip
    if not out:
        return ToolResult(
            ok=True, summary="У аналитиков Альфа-Банка нет материалов по теме", data={"found": 0}
        )
    return ToolResult(
        ok=True,
        summary=f"Найдено фрагментов аналитики Альфа-Банка: {len(out)}",
        evidence=out,
        data={"found": len(out)},
    )


def _macro_title(a: MacroArgs) -> str:
    return (
        "Проверяю ключевую ставку"
        if a.indicator == "key_rate"
        else f"Проверяю курс {a.currency or ''}".strip()
    )


def _signed(value: float | None, unit: str) -> str:
    if value is None:
        return "нет данных"
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.2f}".replace(".", ",") + f" {unit}"


@tool(
    "get_macro",
    "Данные Банка России: ключевая ставка или официальный курс валюты — последнее значение, изменение за 7 и 30 дней, минимум и максимум.",
    MacroArgs,
    _macro_title,
)
def get_macro(ctx: AgentContext, args: MacroArgs) -> ToolResult:
    if args.indicator == "fx" and args.currency is None:
        raise ToolFailure("Для indicator=fx укажите currency: " + ", ".join(CURRENCIES))
    indicator = "key_rate" if args.indicator == "key_rate" else f"fx_{(args.currency or '').lower()}"
    s = MacroStore(ctx.app.db).summary(indicator, days=args.days, weekly=True)
    if s is None:
        raise ToolFailure("Данных ЦБ по этому показателю нет")
    num = lambda v: f"{v:.2f}".replace(".", ",").removesuffix(",00")  # noqa: E731
    if args.indicator == "key_rate":
        name, unit_v, unit_d = "Ключевая ставка Банка России", "%", "п.п."
    else:
        name, unit_v, unit_d = f"Официальный курс {CURRENCY_RU[args.currency or '']} (ЦБ)", " ₽", "₽"  # type: ignore[index]
    when = s.latest.date.strftime("%d.%m.%Y")
    text = (
        f"{name} на {when}: {num(s.latest.value)}{unit_v}. "
        f"Изменение за 7 дней: {_signed(s.change_7d, unit_d)}, за 30 дней: {_signed(s.change_30d, unit_d)}. "
        f"Минимум и максимум за {args.days} дней: {num(s.min_90d)}{unit_v} и {num(s.max_90d)}{unit_v}."
    )
    out: list[EvidenceItem] = []
    _add(
        ctx, out, source_id=f"cbr:{indicator}:{s.latest.date.isoformat()}", kind="cbr", title=name, text=text,
        publisher="Банк России", published_at=datetime(s.latest.date.year, s.latest.date.month, s.latest.date.day, tzinfo=UTC),
        meta={"indicator": indicator, "source": s.source},
    )  # fmt: skip
    return ToolResult(
        ok=True,
        summary=f"{name}: {num(s.latest.value)}{unit_v} на {when}, за 30 дней {_signed(s.change_30d, unit_d)}",
        evidence=out,
        data={"latest": s.latest.value, "series": [[p.date.isoformat(), p.value] for p in s.series[-14:]]},
    )


@tool(
    "get_related_group",
    "Другие компании той же группы (холдинга), если компания в неё входит.",
    NoArgs,
    "Смотрю компании группы",
)
def get_related_group(ctx: AgentContext, args: NoArgs) -> ToolResult:
    if not ctx.profile.group_id:
        return ToolResult(ok=True, summary="Компания не входит в группу")
    members = ctx.app.profiles.group_members(ctx.company_id)
    if not members:
        return ToolResult(ok=True, summary="Других компаний группы в данных нет")
    lines = [
        f"{m['name']} — {lower_name(m['industry_name'])}"
        + (f", {m['region_name']}" if m["region_name"] else "")
        for m in members
    ]
    out: list[EvidenceItem] = []
    _add(
        ctx, out, source_id=f"data:{ctx.company_id}:group", kind="client_data", title="Компании группы",
        text=f"Компания входит в группу, ещё {len(members)} компаний:\n" + "\n".join(lines),
    )  # fmt: skip
    return ToolResult(
        ok=True, summary=f"В группе ещё {len(members)} компаний", evidence=out,
        data={"members": [{"name": m["name"], "industry_id": m["industry_id"]} for m in members]},
    )  # fmt: skip


@tool(
    "submit_insight",
    "Передать готовый персональный разбор события (InsightDraft). Вызывается один раз в конце.",
    InsightDraft,
    "Черновик готов",
    kinds=INSIGHT_KINDS,
    terminal=True,
)
def submit_insight(ctx: AgentContext, args: InsightDraft) -> ToolResult:
    claims = len(args.claims())
    return ToolResult(
        ok=True, summary=f"Черновик готов, утверждений: {claims}", data={"value": args.model_dump()}
    )


@tool(
    "submit_answer",
    "Передать ответ клиенту (ChatAnswer). Вызывается один раз в конце.",
    ChatAnswer,
    "Ответ готов",
    kinds=CHAT_KINDS,
    terminal=True,
)
def submit_answer(ctx: AgentContext, args: ChatAnswer) -> ToolResult:
    return ToolResult(
        ok=True, summary=f"Ответ готов, блоков: {len(args.blocks)}", data={"value": args.model_dump()}
    )


@tool(
    "open_evidence",
    "Полный текст источника по его идентификатору (до 4000 символов).",
    OpenEvidenceArgs,
    "Открываю источник",
    kinds=CHAT_KINDS,
)
def open_evidence(ctx: AgentContext, args: OpenEvidenceArgs) -> ToolResult:
    item = ctx.evidence.get(args.eid)
    if item is None:
        raise ToolFailure(f"Источника {args.eid} нет в этом разборе")
    return ToolResult(
        ok=True,
        summary=f"{EvidenceRegistry.kind_label(item)}: {item.title}",
        data={"eid": item.eid, "text": untrusted_wrap(item, item.full_text or item.text)},
    )


# ── выполнение ──
def tool_specs(names: list[str]) -> list[ToolSpec]:
    return [
        ToolSpec(name=n, description=TOOLS[n].description, parameters=to_llm_schema(TOOLS[n].args_model))
        for n in names
    ]


def tools_for(kind: str) -> list[str]:
    return [n for n, t in TOOLS.items() if kind in t.kinds]


def _scope_error(ctx: AgentContext, args: BaseModel) -> str | None:
    tax = ctx.app.taxonomy
    event_id = getattr(args, "event_id", None)
    if event_id is not None and event_id not in ctx.allowed_event_ids:
        return f"Событие {event_id} недоступно в этом разборе"
    industries = list(getattr(args, "industry_ids", None) or [])
    if getattr(args, "industry_id", None):
        industries.append(args.industry_id)  # type: ignore[attr-defined]
    for iid in industries:
        if iid not in tax.industries:
            return f"Неизвестная отрасль {iid!r}: используйте industry_id из справочника"
    for fid in getattr(args, "factor_ids", None) or []:
        if fid not in tax.factors:
            return f"Неизвестный фактор {fid!r}: используйте factor_id из справочника"
    return None


def _safe_title(spec: Tool, args: BaseModel | None) -> str:
    try:
        return spec.title(args if args is not None else spec.args_model.model_construct())
    except (AttributeError, KeyError, TypeError):
        return spec.title.__name__ if spec.title.__name__ != "<lambda>" else spec.name


def _validation_text(exc: ValidationError) -> str:
    parts = []
    for e in exc.errors()[:5]:
        loc = ".".join(str(x) for x in e["loc"]) or "аргументы"
        parts.append(f"{loc}: {e['msg']}")
    return "Неверные аргументы — " + "; ".join(parts)


async def execute_tool_call(ctx: AgentContext, call: ToolCall) -> ToolResult:
    """Проверки §5.2 → выполнение с таймаутом → трасса. Ошибки не бросаются, а возвращаются модели."""
    spec = TOOLS.get(call.name)
    if spec is None or ctx.kind not in spec.kinds:
        return ToolResult(
            ok=False, summary="Инструмент недоступен", error=f"Инструмент {call.name} недоступен"
        )
    if not spec.terminal and ctx.tool_calls >= ctx.limits.max_tool_calls:
        return ToolResult(
            ok=False,
            summary="Лимит вызовов исчерпан",
            error="Лимит вызовов инструментов исчерпан — передайте результат через submit_insight",
        )
    if not spec.terminal:
        ctx.tool_calls += 1
    if "__raw__" in call.arguments:
        args_err: str | None = "Аргументы не являются корректным JSON"
        args = None
    else:
        try:
            args = spec.args_model.model_validate(call.arguments)
            args_err = None
        except ValidationError as exc:
            args, args_err = None, _validation_text(exc)
    title = _safe_title(spec, args)
    shown_args = {} if spec.terminal else call.arguments
    ctx.trace.emit("tool.call", "tools", title, payload={"tool": call.name, "args": shown_args})
    started = time.monotonic()
    error = args_err or (_scope_error(ctx, args) if args is not None else None)
    if error is None:
        try:
            result = await asyncio.wait_for(asyncio.to_thread(spec.run, ctx, args), TOOL_TIMEOUT_S)
        except ToolFailure as exc:
            error = str(exc)
        except TimeoutError:
            error = "Инструмент не ответил вовремя"
        except Exception as exc:
            error = f"Внутренняя ошибка инструмента ({type(exc).__name__})"
    if error is not None:
        result = ToolResult(ok=False, summary=error, error=error)
    duration = int((time.monotonic() - started) * 1000)
    for item in result.evidence:
        ctx.trace.emit(
            "evidence.added", "tools",
            f"Источник: {item.publisher or item.title}" + (f", {_day(item.published_at)}" if item.published_at else ""),
            payload={"eid": item.eid, "source_id": item.source_id, "kind": item.kind, "title": item.title},
        )  # fmt: skip
    ctx.trace.emit(
        "tool.result", "tools", result.summary, status="ok" if result.ok else "warn",
        payload={"tool": call.name, "summary": result.summary, "eids": [e.eid for e in result.evidence],
                 "duration_ms": duration, "ok": result.ok},
    )  # fmt: skip
    return result


def _evidence_for_model(item: EvidenceItem, text_limit: int | None) -> dict[str, Any]:
    text = (
        item.text
        if text_limit is None or len(item.text) <= text_limit
        else item.text[:text_limit].rstrip() + " […]"
    )
    return {
        "eid": item.eid,
        "kind": item.kind,
        "title": item.title,
        "date": item.published_at.date().isoformat() if item.published_at else None,
        "text": untrusted_wrap(item, text),
    }


def result_for_model(result: ToolResult, limit: int = MAX_RESULT_CHARS) -> str:
    """Компактный JSON для сообщения `tool` (§5.3), не длиннее `limit` символов."""
    if not result.ok:
        return json.dumps({"ok": False, "error": result.error or result.summary}, ensure_ascii=False)

    def dump(text_limit: int | None, with_data: bool, n_evidence: int, truncated: bool) -> str:
        body: dict[str, Any] = {
            "ok": True,
            "summary": result.summary,
            "evidence": [_evidence_for_model(e, text_limit) for e in result.evidence[:n_evidence]],
            "data": result.data if with_data else {},
        }
        if truncated:
            body["truncated"] = True
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"), default=str)

    n = len(result.evidence)
    text = dump(None, True, n, False)
    if len(text) <= limit:
        return text
    for text_limit in (1000, 600, 300, 150):
        text = dump(text_limit, True, n, True)
        if len(text) <= limit:
            return text
    text = dump(150, False, n, True)
    while len(text) > limit and n > 0:
        n -= 1
        text = dump(150, False, n, True)
    return text
