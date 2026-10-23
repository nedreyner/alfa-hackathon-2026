from __future__ import annotations

from pathlib import Path

import pytest

from alfa_insight.appctx import build_context
from alfa_insight.ingest.extract import content_hash
from alfa_insight.ingest.schemas import NewsTagging
from alfa_insight.ingest.tagging import postprocess, tag_batch
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.settings import Settings
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.timeutil import to_iso, utc_now

ROOT = Path(__file__).resolve().parents[4]


def test_postprocess_drops_unknown_and_scales() -> None:
    tax = Taxonomy(ROOT / "data" / "reference")
    raw = NewsTagging.model_validate(
        {
            "is_business_relevant": True,
            "summary": " Пошлины растут. ",
            "event_type": "no_such_type",
            "importance": 4,
            "horizon": "months",
            "industries": [
                {
                    "industry_id": "metallurgy",
                    "effect": "prices_up",
                    "impact": 2,
                    "confidence": 3,
                    "rationale": "a",
                },
                {
                    "industry_id": "metallurgy",
                    "effect": "prices_up",
                    "impact": 3,
                    "confidence": 1,
                    "rationale": "b",
                },
                {
                    "industry_id": "space_mining",
                    "effect": "prices_up",
                    "impact": 3,
                    "confidence": 3,
                    "rationale": "c",
                },
            ],
            "factors": [
                {
                    "factor_id": "customs_tariffs",
                    "direction": "up",
                    "impact": 3,
                    "confidence": 3,
                    "rationale": "d",
                },
                {
                    "factor_id": "moon_phase",
                    "direction": "down",
                    "impact": 1,
                    "confidence": 1,
                    "rationale": "e",
                },
                {
                    "factor_id": "key_rate",
                    "direction": "down",
                    "impact": 1,
                    "confidence": 2,
                    "rationale": "f",
                },
            ],
            "geo": ["ru", "RU-MOW", "Китай", "CN"],
        }
    )
    clean = postprocess(raw, tax)
    assert clean.event_type == "other" and clean.summary == "Пошлины растут."
    assert [(i.industry_id, i.impact, i.confidence) for i in clean.industries] == [("metallurgy", 1.0, 0.33)]
    assert {f.factor_id: (f.direction, f.impact) for f in clean.factors} == {
        "customs_tariffs": (1, 1.0),
        "key_rate": (-1, 0.33),
    }
    assert clean.geo == ["RU", "RU-MOW", "CN"]
    assert set(clean.warnings) == {"industry:space_mining", "factor:moon_phase", "event_type:no_such_type"}


NEWS = [
    (
        "Минпромторг предложил повысить пошлины на арматуру",
        "Ввозная пошлина на арматуру и металлопрокат вырастет до 15%, сталь подорожает.",
    ),
    (
        "ЦБ сохранил ключевую ставку 14%",
        "Банк России сохранил ключевую ставку на уровне 14% годовых, кредит остаётся дорогим.",
    ),
    ("Певец дал концерт", "Звезда эстрады выступила перед поклонниками."),
]


@pytest.fixture
def ctx(settings: Settings):  # type: ignore[no-untyped-def]
    c = build_context(settings)
    c.set_router(build_router(settings, c.db, backend=FakeBackend()))
    return c


async def test_tag_batch_fake(ctx) -> None:  # type: ignore[no-untyped-def]
    store = NewsStore(ctx.db)
    now = to_iso(utc_now())
    ids = store.insert(
        NewsIn(
            source_id="interfax",
            origin="rss",
            external_id=str(i),
            url=f"https://x.ru/{i}",
            title=t,
            body=b,
            body_source="full",
            publisher="Интерфакс",
            trust=0.9,
            published_at=now,
            fetched_at=now,
            content_hash=content_hash(t, b),
            status="extracted",
        )
        for i, (t, b) in enumerate(NEWS)
    )
    tagged, filtered, failed, cost = await tag_batch(ctx, [store.get(i) for i in ids])
    assert (tagged, filtered, failed, cost) == (2, 1, 0, 0.0)
    metal = store.industries(ids[0])
    assert metal and metal[0]["industry_id"] in {"metallurgy", "wholesale_metals"}
    assert {i["industry_id"] for i in metal} >= {"metallurgy"}
    tags = store.tags(ids[1])
    assert tags and tags["payload"]["event_type"] == "monetary_policy" and tags["model"] == "fake"
    assert any(f["factor_id"] == "key_rate" for f in tags["payload"]["factors"])
    assert store.get(ids[2]).status == "filtered_out"  # type: ignore[union-attr]
    assert ctx.db.scalar("SELECT count(*) FROM news_fts WHERE news_fts MATCH 'арматура'") == 1
    assert tags["prompt_version"].startswith("tagging_v1+tx")
