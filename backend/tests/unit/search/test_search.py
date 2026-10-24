from __future__ import annotations

from alfa_insight.search.fts import build_match
from alfa_insight.search.news import search_news
from alfa_insight.search.research import search_research
from alfa_insight.store.events import EventStore
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.store.research import ResearchStore
from alfa_insight.text.lemmatizer import lemmas_str
from alfa_insight.timeutil import to_iso, utc_now


def test_build_match() -> None:
    assert build_match("Пошлины на импорт металлопроката") == '"пошлина" OR "импорт" OR "металлопрокат"'
    assert build_match("и в на") is None
    assert build_match("") is None
    assert build_match('сталь "кавычки"') == '"сталь" OR "кавычка"'
    assert build_match(" ".join(f"слово{i}" for i in range(40)), max_terms=3).count(" OR ") == 2


def test_search_news_on_seed(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    hits = search_news(
        seeded_ctx.db, "выплавка стали металлургия", company_id="SYN-DEMO-01", days=60, limit=5
    )
    assert hits
    top3 = [h.title.lower() for h in hits[:3]]
    assert any("стал" in t or "металл" in t for t in top3)
    events = [h.event_id for h in hits]
    assert len(events) == len(set(events))  # по одному результату на событие
    fuel = search_news(
        seeded_ctx.db, "экспорт дизельного топлива", company_id="SYN-DEMO-06", days=60, limit=3
    )
    assert fuel and any("дизел" in h.title.lower() or "топлив" in h.title.lower() for h in fuel)


def test_private_news_isolated(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    store = NewsStore(seeded_ctx.db)
    now = to_iso(utc_now())
    [nid] = store.insert(
        [
            NewsIn(
                source_id="user",
                origin="user",
                title="Уникальный квазитермин закупка",
                body="квазитермин",
                body_source="user",
                publisher="Пользователь",
                trust=0.5,
                published_at=now,
                fetched_at=now,
                status="tagged",
                owner_company_id="SYN-DEMO-02",
            )
        ]
    )
    seeded_ctx.db.execute(
        "INSERT INTO news_fts(rowid, title_lemmas, body_lemmas) VALUES (?, ?, ?)",
        (nid, lemmas_str("Уникальный квазитермин закупка"), "квазитермин"),
    )
    assert search_news(seeded_ctx.db, "квазитермин", company_id="SYN-DEMO-02")
    assert not search_news(seeded_ctx.db, "квазитермин", company_id="SYN-DEMO-01")
    assert EventStore(seeded_ctx.db).list_ids()  # события seed есть


def test_search_research_boost(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    store = ResearchStore(seeded_ctx.db)
    doc = store.create_doc(
        slug="t", title="Тест", published_at="2026-09-11", file_name="t.pdf", sha256="x", pages=1, url=None
    )
    texts = {
        1: "Ключевая ставка останется на уровне 14% до конца года, кредит дорогой.",
        2: "Ключевая ставка и спрос на металлопрокат: мы ожидаем стабилизации цен на сталь.",
    }
    ids = {}
    for n, text in texts.items():
        ids[n] = store.add_chunk(
            doc,
            source_id=f"alfa:t:p1:c{n}",
            page=1,
            chunk_no=n,
            kind="text",
            heading="Ставка",
            text=text,
            heading_lemmas=lemmas_str("Ставка"),
            text_lemmas=lemmas_str(text),
        )
    store.add_items(
        ids[2],
        [
            {
                "kind": "position",
                "statement": "ожидаем стабилизации",
                "industries": ["metallurgy"],
                "factors": [],
                "confidence": 0.8,
            }
        ],
    )
    plain = search_research(seeded_ctx.db, "ключевая ставка", limit=2)
    boosted = search_research(seeded_ctx.db, "ключевая ставка", industry_ids=["metallurgy"], limit=2)
    assert boosted[0].source_id == "alfa:t:p1:c2" and boosted[0].items[0].kind == "position"
    assert {h.source_id for h in plain} == {"alfa:t:p1:c1", "alfa:t:p1:c2"}
