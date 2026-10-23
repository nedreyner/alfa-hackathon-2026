from __future__ import annotations

from datetime import timedelta

import pytest

from alfa_insight.appctx import build_context
from alfa_insight.ingest.clustering import cluster_tagged
from alfa_insight.ingest.schemas import CleanTagging, EntityTag, StoredFactor, StoredIndustry
from alfa_insight.settings import Settings
from alfa_insight.store.events import EventStore
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.text.lemmatizer import lemmas_str
from alfa_insight.timeutil import to_iso, utc_now

BASE = utc_now() - timedelta(hours=10)


def tag(
    summary: str, event_type: str, importance: int, industries=(), factors=(), entities=()
) -> CleanTagging:  # type: ignore[no-untyped-def]
    return CleanTagging(
        is_business_relevant=True,
        summary=summary,
        event_type=event_type,
        importance=importance,
        horizon="weeks",
        industries=[
            StoredIndustry(industry_id=i, effect=e, impact=imp, confidence=c) for i, e, imp, c in industries
        ],
        factors=[
            StoredFactor(factor_id=f, direction=d, impact=imp, confidence=c) for f, d, imp, c in factors
        ],
        geo=["RU"],
        entities=[EntityTag(kind="gov", name=n) for n in entities],
        key_numbers=[],
        injection_suspected=False,
    )


STORIES = [
    # (publisher, trust, title, tagging)
    (
        "Интерфакс",
        0.9,
        "Минпромторг предложил повысить пошлины на импорт арматуры",
        tag(
            "Минпромторг предложил повысить ввозные пошлины на арматуру до 15%.",
            "tariffs_customs",
            3,
            [("metallurgy", "prices_up", 0.67, 0.67)],
            [("customs_tariffs", 1, 0.67, 0.67)],
            ["Минпромторг"],
        ),
    ),
    (
        "ТАСС",
        0.9,
        "Пошлины на импорт арматуры могут вырасти до 15%",
        tag(
            "Ввозные пошлины на арматуру могут вырасти до 15%, предложил Минпромторг.",
            "tariffs_customs",
            4,
            [("wholesale_metals", "costs_up", 1.0, 0.67)],
            [("customs_tariffs", 1, 1.0, 1.0)],
            ["Минпромторг"],
        ),
    ),
    (
        "Ведомости",
        0.95,
        "Минпромторг хочет поднять пошлины на арматуру",
        tag(
            "Минпромторг предложил поднять пошлины на ввоз арматуры до 15%.",
            "tariffs_customs",
            3,
            [("metallurgy", "prices_up", 1.0, 0.33)],
            [],
            ["Минпромторг"],
        ),
    ),
    (
        "Банк России",
        1.0,
        "Банк России сохранил ключевую ставку на уровне 14%",
        tag(
            "Совет директоров Банка России сохранил ключевую ставку на уровне 14% годовых.",
            "monetary_policy",
            5,
            [],
            [("key_rate", 1, 1.0, 1.0)],
            ["Банк России"],
        ),
    ),
    (
        "ПРАЙМ",
        0.85,
        "ЦБ сохранил ключевую ставку 14%",
        tag(
            "Банк России сохранил ключевую ставку на уровне 14% годовых.",
            "monetary_policy",
            5,
            [],
            [("key_rate", -1, 0.67, 0.33)],
            ["Банк России"],
        ),
    ),
    (
        "Интерфакс",
        0.9,
        "Правительство продлило запрет на экспорт бензина",
        tag(
            "Правительство продлило запрет на экспорт бензина до конца года.",
            "trade_policy",
            4,
            [("wholesale_fuel", "supply_up", 0.67, 0.67)],
            [],
            ["Правительство РФ"],
        ),
    ),
    (
        "Коммерсантъ",
        0.9,
        "Запрет на экспорт бензина продлён до конца года",
        tag(
            "Запрет на экспорт бензина продлён правительством до конца года.",
            "trade_policy",
            4,
            [("wholesale_fuel", "supply_up", 0.67, 1.0)],
            [],
            ["Правительство РФ"],
        ),
    ),
    (
        "ТАСС",
        0.9,
        "Урожай пшеницы на Кубани превысил прогноз",
        tag(
            "Урожай пшеницы в Краснодарском крае превысил прогноз аграриев.",
            "industry_statistics",
            2,
            [("agriculture", "supply_up", 0.67, 0.67)],
            [],
            [],
        ),
    ),
    (
        "ПРАЙМ",
        0.85,
        "Ритейлеры отчитались о росте продаж бытовой техники",
        tag(
            "Продажи бытовой техники в сетях выросли на 9% за квартал.",
            "demand_shift",
            2,
            [("retail", "demand_up", 0.67, 0.67)],
            [],
            [],
        ),
    ),
]


@pytest.fixture
def ctx(settings: Settings):  # type: ignore[no-untyped-def]
    return build_context(settings)


def _insert(ctx, items, origin: str = "rss", owner: str | None = None, start: int = 0) -> list[int]:  # type: ignore[no-untyped-def]
    store = NewsStore(ctx.db)
    ids = []
    for i, (publisher, trust, title, tg) in enumerate(items, start):
        ts = to_iso(BASE + timedelta(minutes=10 * i))
        [nid] = store.insert(
            [
                NewsIn(
                    source_id=publisher,
                    origin=origin,
                    external_id=f"{origin}{i}",
                    url=None if origin == "user" else f"https://n.ru/{origin}/{i}",
                    title=title,
                    body=tg.summary,
                    body_source="full",
                    publisher=publisher,
                    trust=trust,
                    published_at=ts,
                    fetched_at=ts,
                    status="extracted",
                    owner_company_id=owner,
                )
            ]
        )
        store.save_tags(
            nid,
            tg,
            model="fake",
            prompt_version="t",
            title_lemmas=lemmas_str(title),
            body_lemmas=lemmas_str(tg.summary),
            status="tagged",
        )
        ids.append(nid)
    return ids


def test_three_stories_and_aggregates(ctx) -> None:  # type: ignore[no-untyped-def]
    ids = _insert(ctx, STORIES)
    joined, created = cluster_tagged(ctx)
    assert (joined, created) == (4, 5)
    events = EventStore(ctx.db)
    by_news = {nid: NewsStore(ctx.db).get(nid).event_id for nid in ids}  # type: ignore[union-attr]
    metal = events.get(by_news[ids[0]])
    assert metal is not None
    assert by_news[ids[1]] == by_news[ids[2]] == metal.id
    assert by_news[ids[3]] == by_news[ids[4]] and by_news[ids[5]] == by_news[ids[6]]
    assert len({by_news[i] for i in ids}) == 5  # пшеница и техника — отдельно
    assert metal.publisher_count == 3 and metal.news_count == 3
    assert metal.importance == 5  # max(4) + 1 за три издания
    assert metal.lead_news_id == ids[2] and metal.title.startswith("Минпромторг хочет")  # максимальный trust
    sig = events.load_signals([metal.id])[0]
    assert {(i.industry_id, i.effect) for i in sig.industries} == {
        ("metallurgy", "prices_up"),
        ("wholesale_metals", "costs_up"),
    }
    met = next(i for i in sig.industries if i.industry_id == "metallurgy")
    assert (met.impact, met.confidence) == (1.0, 0.67)
    rate = events.load_signals([by_news[ids[3]]])[0]
    assert rate.factors[0].direction == 1 and rate.importance == 5 and rate.publisher_count == 2
    multi = [e for e in events.load_signals(events.list_ids()) if e.publisher_count >= 2]
    assert len(multi) == 3
    assert ctx.db.scalar("SELECT count(*) FROM events_fts WHERE events_fts MATCH 'арматура'") == 1


def test_private_events_isolated(ctx) -> None:  # type: ignore[no-untyped-def]
    pub = _insert(ctx, STORIES[:1])
    priv = _insert(ctx, STORIES[1:2], origin="user", owner="SYN-DEMO-01")
    later = _insert(
        ctx,
        [("ПРАЙМ", 0.85, "Минпромторг предложил повысить пошлины на импорт арматуры", STORIES[0][3])],
        start=5,
    )
    cluster_tagged(ctx)
    store, events = NewsStore(ctx.db), EventStore(ctx.db)
    e_pub, e_priv, e_later = (store.get(i[0]).event_id for i in (pub, priv, later))  # type: ignore[union-attr]
    assert e_pub == e_later and e_priv != e_pub
    ev = events.get(e_priv)  # type: ignore[arg-type]
    assert (
        ev is not None
        and ev.visibility == "private"
        and ev.owner_company_id == "SYN-DEMO-01"
        and ev.news_count == 1
    )
