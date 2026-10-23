"""Разметка новостей LLM (docs/06-ingestion-search.md §8) и FakeLLM-эвристики для неё (04-llm §9)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from alfa_insight.appctx import AppContext
from alfa_insight.errors import BudgetExceeded, LLMError
from alfa_insight.ingest.schemas import (
    SCALE,
    CleanTagging,
    FactorImpactTag,
    IndustryImpactTag,
    NewsTagging,
    StoredFactor,
    StoredIndustry,
)
from alfa_insight.llm.fake import fake_handler
from alfa_insight.llm.types import LLMRequest, Priority
from alfa_insight.log import get_logger
from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy
from alfa_insight.store.news import NewsRow, NewsStore
from alfa_insight.text.lemmatizer import lemmas_str, lemmatize
from alfa_insight.text.numbers import extract_numbers

log = get_logger("ingest.tagging")
TAG_CONCURRENCY = 4
MAX_TAG_ATTEMPTS = 3
_GEO = re.compile(r"^(?:[A-Z]{2}|RU-[A-Z]{2,3})$")


def taxonomy_ctx(tax: Taxonomy) -> dict[str, Any]:
    return {
        "industries": [i for i in tax.industries.values() if i.id != UNKNOWN],
        "factors": list(tax.factors.values()),
        "event_types": list(tax.event_types.values()),
        "effects": [{"id": k, "meaning": v} for k, v in tax.effects.items()],
    }


def render_tagging(ctx: AppContext, row: NewsRow) -> tuple[str, list[Any]]:
    rendered = ctx.prompts.render(
        "tagging",
        publisher=row.publisher,
        published_at=row.published_at,
        categories=row.rss_categories,
        title=row.title,
        body=(row.body or "")[: ctx.settings.tag_body_chars],
        **taxonomy_ctx(ctx.taxonomy),
    )
    return rendered.version, rendered.messages


def postprocess(tag: NewsTagging, tax: Taxonomy) -> CleanTagging:
    warnings: list[str] = []
    industries: dict[tuple[str, str], StoredIndustry] = {}
    for it in tag.industries:
        if it.industry_id not in tax.industries or it.industry_id == UNKNOWN:
            warnings.append(f"industry:{it.industry_id}")
            continue
        key = (it.industry_id, it.effect)
        cand = StoredIndustry(
            industry_id=it.industry_id,
            effect=it.effect,
            impact=SCALE[it.impact],
            confidence=SCALE[it.confidence],
            rationale=it.rationale,
        )
        if key not in industries or cand.impact > industries[key].impact:
            industries[key] = cand
    factors: dict[str, StoredFactor] = {}
    for f in tag.factors:
        if f.factor_id not in tax.factors:
            warnings.append(f"factor:{f.factor_id}")
            continue
        cand_f = StoredFactor(
            factor_id=f.factor_id,
            direction=1 if f.direction == "up" else -1,
            impact=SCALE[f.impact],
            confidence=SCALE[f.confidence],
            rationale=f.rationale,
        )
        if f.factor_id not in factors or cand_f.impact > factors[f.factor_id].impact:
            factors[f.factor_id] = cand_f
    event_type = tag.event_type if tag.event_type in tax.event_types else "other"
    if event_type != tag.event_type:
        warnings.append(f"event_type:{tag.event_type}")
    geo = list(dict.fromkeys(g.upper() for g in tag.geo if _GEO.match(g.upper())))
    if warnings:
        log.warning("tagging_unknown_ids", ids=warnings)
    return CleanTagging(
        is_business_relevant=tag.is_business_relevant,
        summary=tag.summary.strip(),
        event_type=event_type,
        importance=tag.importance,
        horizon=tag.horizon,
        industries=list(industries.values()),
        factors=list(factors.values()),
        geo=geo,
        entities=tag.entities,
        key_numbers=tag.key_numbers,
        injection_suspected=tag.injection_suspected,
        warnings=warnings,
    )


async def tag_one(
    ctx: AppContext,
    row: NewsRow,
    *,
    task: str = "tagging",
    priority: Priority | None = None,
    run_id: str | None = None,
) -> tuple[CleanTagging, str, str, float]:
    """Разметить одну новость: (разметка, модель, версия промпта, стоимость)."""
    version, messages = render_tagging(ctx, row)
    res = await ctx.router.structured(
        task=task,  # type: ignore[arg-type]
        messages=messages,
        schema=NewsTagging,
        prompt_version=version,
        priority=priority,
        run_id=run_id,
    )
    return postprocess(res.value, ctx.taxonomy), res.raw.model_key, version, res.raw.usage.cost_rub


def save_tagging(store: NewsStore, row: NewsRow, clean: CleanTagging, model: str, version: str) -> str:
    status = "tagged" if clean.is_business_relevant else "filtered_out"
    store.save_tags(
        row.id,
        clean,
        model=model,
        prompt_version=version,
        title_lemmas=lemmas_str(row.title),
        body_lemmas=lemmas_str(f"{clean.summary}\n{row.body or ''}"),
        status=status,
    )
    return status


async def tag_batch(
    ctx: AppContext, rows: list[NewsRow], *, max_cost_rub: float | None = None
) -> tuple[int, int, int, float]:
    """Разметить пачку новостей: (tagged, filtered_out, failed, стоимость)."""
    store = NewsStore(ctx.db)
    sem = asyncio.Semaphore(TAG_CONCURRENCY)
    spent = 0.0
    counts = {"tagged": 0, "filtered_out": 0, "failed": 0}
    stop = asyncio.Event()

    async def one(row: NewsRow) -> None:
        nonlocal spent
        if stop.is_set():
            return
        async with sem:
            if stop.is_set():
                return
            try:
                clean, model, version, cost = await tag_one(ctx, row)
            except BudgetExceeded:
                stop.set()
                return
            except LLMError as exc:
                attempts = store.bump_attempt(row.id, f"{exc.code}: {exc.message}")
                if attempts >= MAX_TAG_ATTEMPTS:
                    store.set_status(row.id, "failed")
                    counts["failed"] += 1
                return
            spent += cost
            counts[save_tagging(store, row, clean, model, version)] += 1
            if max_cost_rub is not None and spent >= max_cost_rub:
                stop.set()

    await asyncio.gather(*(one(r) for r in rows))
    return counts["tagged"], counts["filtered_out"], counts["failed"], spent


# ── FakeLLM: детерминированная разметка по ключевым словам ──
FACTOR_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("key_rate", ("ключевой ставка", "ключевая ставка", "ставка цб", "денежно-кредитный")),
    ("inflation", ("инфляция",)),
    ("fx_cny", ("юань",)),
    ("fx_usd", ("доллар",)),
    ("fx_eur", ("евро ",)),
    ("fx_inr", ("рупия",)),
    ("fx_try", ("лира",)),
    ("fx_kzt", ("тенге",)),
    ("sanctions", ("санкция",)),
    ("customs_tariffs", ("пошлина", "утильсбор", "квота")),
    ("logistics", ("логистика", "перевозка", "фрахт")),
    ("tax_burden", ("налог", "ндпи", "акциз", "ндс")),
    ("gov_spending", ("госзакупка", "госзаказ", "нацпроект")),
    ("mortgage_market", ("ипотека",)),
    ("oil_prices", ("нефть",)),
    ("energy_prices", ("электроэнергия", "тариф на газ")),
    ("credit_conditions", ("кредитование", "кредит ")),
    ("labor_costs", ("зарплата", "дефицит кадр")),
]
EVENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("monetary_policy", ("ключевой ставка", "ключевая ставка", "ставка цб")),
    ("tariffs_customs", ("пошлина", "утильсбор")),
    ("sanctions", ("санкция",)),
    ("trade_policy", ("запрет экспорт", "экспорт", "импорт", "квота")),
    ("tax_change", ("налог", "ндпи", "акциз")),
    ("inflation_data", ("инфляция",)),
    ("fx_market", ("курс", "юань", "доллар")),
    ("real_estate_market", ("ипотека", "застройщик", "жилье")),
    ("government_support", ("субсидия", "льгота", "господдержка")),
    ("regulation", ("маркировка", "требование", "регулирование", "закон")),
    ("commodity_prices", ("цена", "нефть", "бензин", "топливо")),
    ("credit_market", ("кредит",)),
]
EFFECT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("supply_down", ("запрет", "дефицит", "перебой", "авария")),
    ("support_measures", ("субсидия", "льгота", "поддержка")),
    ("costs_up", ("пошлина", "налог", "утильсбор", "сбор", "акциз")),
    ("regulation_tighter", ("маркировка", "требование", "регулирование")),
    ("demand_down", ("снижение спрос", "падение спрос", "спрос снизиться", "спрос упасть")),
    ("demand_up", ("рост спрос", "спрос вырасти")),
    ("prices_down", ("подешеветь", "снижение цена", "цена снизиться")),
    ("prices_up", ("подорожать", "рост цена", "цена вырасти", "повысить", "рост")),
]
DOWN_WORDS = ("снизить", "снижение", "понизить", "смягчение", "смягчить", "сократить", "упасть", "отменить")


def _has(text: str, needles: tuple[str, ...]) -> bool:
    return any(n in text for n in needles)


def _extract_news(req: LLMRequest) -> tuple[str, str]:
    user = next((m.text() for m in reversed(req.messages) if m.role == "user"), "")
    m = re.search(r"<untrusted_document[^>]*>\n?(.*?)\n?</untrusted_document>", user, re.S)
    text = m.group(1) if m else user
    title, _, body = text.partition("\n\n")
    return title.strip(), body.strip()


@fake_handler("tagging", "tagging_interactive")
def fake_tagging(req: LLMRequest, payload: dict[str, Any]) -> dict[str, Any]:
    from alfa_insight.settings import get_settings

    tax = _fake_taxonomy(get_settings().reference_dir)
    title, body = _extract_news(req)
    lem_title = lemmatize(title)
    lem_all = lemmatize(f"{title}\n{body}")
    joined = " " + " ".join(lem_all) + " "
    joined_title = " " + " ".join(lem_title) + " "
    hits: list[tuple[int, str]] = []
    for ind in tax.industries.values():
        if ind.id == UNKNOWN:
            continue
        n = 0
        for kw in ind.keywords:
            key = " ".join(lemmatize(kw)) or kw.lower()
            n += joined.count(" " + key + " ") + 2 * joined_title.count(" " + key + " ")
        if n:
            hits.append((n, ind.id))
    hits.sort(key=lambda x: (-x[0], x[1]))
    effect = next((e for e, words in EFFECT_RULES if _has(joined, words)), "prices_up")
    industries = [
        IndustryImpactTag(
            industry_id=iid,
            effect=effect,
            impact=min(3, 1 + n // 2),
            confidence=2,
            rationale="совпадение ключевых слов",  # type: ignore[arg-type]
        ).model_dump()
        for n, iid in hits[:3]
    ]
    down = _has(joined, DOWN_WORDS)
    factors = [
        FactorImpactTag(
            factor_id=fid,
            direction="down" if down else "up",
            impact=2,
            confidence=2,
            rationale="ключевое слово",
        ).model_dump()
        for fid, words in FACTOR_RULES
        if _has(joined, words)
    ][:5]
    event_type = next((e for e, words in EVENT_RULES if _has(joined, words)), "other")
    econ = set(tax.prefilter.econ)
    relevant = bool(industries or factors or (set(lem_all) & econ))
    has_numbers = bool(extract_numbers(f"{title} {body}"))
    importance = min(
        5, 2 + int(has_numbers) + int(event_type in ("monetary_policy", "tariffs_customs", "trade_policy"))
    )
    first = re.split(r"(?<=[.!?])\s+", body or title)[0][:380] if (body or title) else title
    return NewsTagging(
        is_business_relevant=relevant,
        summary=first or title[:380],
        event_type=event_type,
        importance=importance if relevant else 1,  # type: ignore[arg-type]
        horizon="weeks",
        industries=industries if relevant else [],  # type: ignore[arg-type]
        factors=factors if relevant else [],  # type: ignore[arg-type]
        geo=["RU"],
        injection_suspected=bool(
            re.search(r"игнорируй|ignore (all )?previous|системн\w+ промпт", f"{title} {body}", re.I)
        ),
    ).model_dump()


_TAX_CACHE: dict[str, Taxonomy] = {}


def _fake_taxonomy(path: Any) -> Taxonomy:
    key = str(path)
    if key not in _TAX_CACHE:
        from alfa_insight.reference.taxonomy import load_taxonomy

        _TAX_CACHE[key] = load_taxonomy(path)
    return _TAX_CACHE[key]
