from __future__ import annotations

import json
from pathlib import Path

import pytest

from alfa_insight.appctx import build_context
from alfa_insight.settings import Settings
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore, SourceIn
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.store.runs import RunStore

EXAMPLE = Path(__file__).resolve().parents[2] / "fixtures" / "agent" / "insight_example.json"


def _event(ctx) -> int:  # type: ignore[no-untyped-def]
    [nid] = NewsStore(ctx.db).insert(
        [
            NewsIn(
                source_id="interfax", origin="rss", external_id="x1", url="https://n.ru/1", title="Арматура дорожает",
                body="Цены на арматуру растут на 8%.", body_source="full", publisher="Интерфакс", trust=0.9,
                published_at="2026-10-22T06:10:00Z", fetched_at="2026-10-22T06:11:00Z", status="extracted",
            )
        ]
    )  # fmt: skip
    return EventStore(ctx.db).create(nid)


def test_save_read_replace(settings: Settings) -> None:
    ctx = build_context(settings)
    store, runs = InsightStore(ctx.db), RunStore(ctx.db)
    event_id = _event(ctx)
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["event"]["id"] = event_id
    store.upsert_sources(
        SourceIn(
            id=s["id"], kind=s["kind"], title=s["title"], publisher=s["publisher"], url=s["url"],
            published_at=s["published_at"], excerpt="x" * 900,
            company_id="SYN-DEMO-02" if s["kind"] == "client_data" else None,
        )
        for s in payload["sources"]
    )  # fmt: skip
    run1 = runs.create(kind="insight", mode="pipeline", company_id="SYN-DEMO-02", event_id=event_id)
    ins_id = store.save(
        insight=payload, verification={"passed": True}, run_id=run1, event_id=event_id,
        confidence=0.81, confidence_level="high", source_ids=[s["id"] for s in payload["sources"]] + ["news:4821"],
    )  # fmt: skip
    row = store.get(ins_id)
    assert (
        row is not None and row.payload["headline"] == payload["headline"] and row.confidence_level == "high"
    )
    assert len(store.insight_source_ids(ins_id)) == 7
    assert store.latest_for("SYN-DEMO-02", event_id, prompt_version="draft@1+verify@1") is not None
    assert store.latest_for("SYN-DEMO-02", event_id, prompt_version="draft@2") is None
    assert set(store.latest_by_events("SYN-DEMO-02", [event_id, 999])) == {event_id}

    # повтор с теми же версиями заменяет инсайт
    payload2 = {**payload, "id": "ins_second", "headline": "Новая версия"}
    run2 = runs.create(kind="insight", mode="pipeline", company_id="SYN-DEMO-02", event_id=event_id)
    store.save(
        insight=payload2, verification={}, run_id=run2, event_id=event_id, confidence=0.4,
        confidence_level="low", source_ids=["news:4821"],
    )  # fmt: skip
    assert store.get(ins_id) is None
    assert store.latest_for("SYN-DEMO-02", event_id).headline == "Новая версия"  # type: ignore[union-attr]

    reviewed = store.review("ins_second", "rejected", "неверные факты")
    assert reviewed is not None and reviewed.status == "rejected" and reviewed.payload["status"] == "rejected"
    assert store.latest_for("SYN-DEMO-02", event_id) is None
    assert store.count_by_status() == {"rejected": 1}


def test_private_sources(settings: Settings) -> None:
    store = InsightStore(build_context(settings).db)
    store.upsert_sources(
        [
            SourceIn(id="data:C1:profile", kind="client_data", title="Профиль", company_id="C1", excerpt="…"),
            SourceIn(id="news:1", kind="news", title="Новость", excerpt="a" * 600),
        ]
    )
    assert store.source("data:C1:profile", company_id="C1") is not None
    assert store.source("data:C1:profile", company_id="C2") is None
    assert store.source("data:C1:profile") is None
    pub = store.source("news:1", company_id="C2")
    assert pub is not None and len(pub.excerpt) == 500
    store.upsert_sources([SourceIn(id="news:1", kind="news", title="Обновлено", excerpt="b")])
    assert store.source("news:1").title == "Обновлено"  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        store.upsert_sources([SourceIn(id="user:5", kind="user_input", title="Текст", excerpt="…")])
