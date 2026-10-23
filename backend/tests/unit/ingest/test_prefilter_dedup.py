from __future__ import annotations

from pathlib import Path

import pytest

from alfa_insight.ingest.dedup import Deduper, DedupIndex
from alfa_insight.ingest.prefilter import Prefilter
from alfa_insight.ingest.sources import load_sources
from alfa_insight.reference.taxonomy import Taxonomy

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def pf() -> Prefilter:
    return Prefilter(Taxonomy(ROOT / "data" / "reference"), min_score=3)


@pytest.fixture(scope="module")
def sources():  # type: ignore[no-untyped-def]
    return load_sources(ROOT / "config")


def test_sport_filtered(pf: Prefilter, sources) -> None:  # type: ignore[no-untyped-def]
    res = pf.score(
        "Сборная выиграла матч чемпионата",
        "Футбольный матч завершился со счётом 2:1.",
        ["Спорт"],
        sources.get("tass"),
        0.9,
    )
    assert not res.passed and "матч" in res.negative and res.category == "rejected"


def test_business_news_passes(pf: Prefilter, sources) -> None:  # type: ignore[no-untyped-def]
    res = pf.score(
        "Минпромторг предложил повысить пошлины на арматуру",
        "Импорт металлопроката вырос, цены на внутреннем рынке снизились.",
        ["Экономика и бизнес"],
        sources.get("tass"),
        0.9,
    )
    assert res.passed and res.category == "allowed"
    assert {"пошлина", "импорт", "цена", "рынок"} <= set(res.econ_hits)
    assert "wholesale_metals" in res.industries or "metallurgy" in res.industries


def test_official_always_passes(pf: Prefilter, sources) -> None:  # type: ignore[no-untyped-def]
    res = pf.score("Объявление о концерте", "Концерт в музее.", [], sources.get("cbr_events"), 1.0)
    assert res.score < 3 and res.passed


def test_soft_categories(pf: Prefilter, sources) -> None:  # type: ignore[no-untyped-def]
    text = ("Банк повысил ставки по кредитам", "Кредит для бизнеса подорожал вслед за ключевой ставкой ЦБ.")
    soft = pf.score(*text, ["Общество"], sources.get("interfax"), 0.9)
    allowed = pf.score(*text, ["Экономика"], sources.get("interfax"), 0.9)
    assert soft.category == "soft" and soft.score == allowed.score - 3 and soft.passed


def test_negative_exception(pf: Prefilter) -> None:
    res = pf.score(
        "Погода испортила урожай",
        "Засуха и погода снизили урожай пшеницы, цены на зерно растут.",
        [],
        None,
        0.9,
    )
    assert "погода" not in res.negative and res.passed


BODY = (
    "Министерство промышленности предложило повысить ввозные пошлины на арматуру и сортовой металлопрокат до "
    "пятнадцати процентов. Мера поддержит российских металлургов и снизит давление импорта на внутренние цены. "
    "Трейдеры переложат часть затрат на строительные компании. Решение рассмотрит правительственная комиссия, "
    "после чего новые ставки вступят в силу. Спрос со стороны девелоперов остаётся слабым из-за дорогой ипотеки. "
    "По данным отраслевого союза, в третьем квартале импорт арматуры из стран Азии вырос почти вдвое. Российские "
    "заводы снизили отпускные цены и предложили покупателям отсрочку платежа. Складские запасы остаются высокими."
)


def test_exact_and_near_duplicates() -> None:
    d = Deduper(max_distance=3)
    index = DedupIndex(simhashes=[], content_hashes={})
    fp1 = d.fingerprint("Пошлины на арматуру", BODY)
    assert d.find_duplicate(index, 1, "h1", fp1) is None
    d.remember(index, 1, "h1", fp1)
    assert d.find_duplicate(index, 2, "h1", fp1) == 1  # точный дубль
    fp3 = d.fingerprint("Пошлины на арматуру", "Москва. " + BODY + " Об этом сообщает агентство.")
    assert d.find_duplicate(index, 3, "h3", fp3) == 1  # перепубликация
    fp4 = d.fingerprint("ЦБ сохранил ставку", "Банк России сохранил ключевую ставку на уровне 14% годовых.")
    assert d.find_duplicate(index, 4, "h4", fp4) is None


def test_stage_marks_duplicates_and_filtered(settings) -> None:  # type: ignore[no-untyped-def]
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.extract import content_hash
    from alfa_insight.ingest.pipeline import stage_prefilter_dedup
    from alfa_insight.store.news import NewsIn, NewsStore
    from alfa_insight.timeutil import to_iso, utc_now

    ctx = build_context(settings)
    store = NewsStore(ctx.db)
    now = to_iso(utc_now())
    texts = [
        ("tass", "Пошлины на арматуру", BODY),
        ("interfax", "Пошлины на арматуру", BODY),  # точный дубль
        ("prime", "Пошлины на арматуру", "Москва. " + BODY + " Об этом сообщает агентство."),
        ("tass", "Сборная выиграла матч", "Футбольный матч чемпионата завершился победой."),
    ]
    ids = store.insert(
        NewsIn(
            source_id=src,
            origin="rss",
            external_id=f"x{i}",
            url=f"https://n.ru/{i}",
            title=t,
            body=b,
            body_source="full",
            publisher=src,
            trust=0.9,
            published_at=now,
            fetched_at=now,
            content_hash=content_hash(t, b),
            status="extracted",
            rss_categories=["Экономика и бизнес"]
            if src == "tass" and i == 0
            else (["Спорт"] if i == 3 else []),
        )
        for i, (src, t, b) in enumerate(texts)
    )
    survivors, stats = stage_prefilter_dedup(ctx, [store.get(i) for i in ids])  # type: ignore[misc]
    assert [r.id for r in survivors] == [ids[0]]
    assert stats.duplicates == 2 and stats.filtered_out == 1
    assert store.get(ids[1]).duplicate_of == ids[0] and store.get(ids[2]).duplicate_of == ids[0]  # type: ignore[union-attr]
    assert store.get(ids[3]).status == "filtered_out"  # type: ignore[union-attr]
