from __future__ import annotations

from pathlib import Path

import pytest

from alfa_insight.appctx import build_context
from alfa_insight.ingest.pipeline import pending_work, pipeline_run
from alfa_insight.ingest.seed import load_seed
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.settings import Settings
from alfa_insight.store.events import EventStore
from alfa_insight.store.news import NewsStore

SEED = Path(__file__).resolve().parents[1] / "fixtures" / "seed_mini.jsonl"
FINAL = {"clustered", "filtered_out", "duplicate", "failed"}


@pytest.fixture
def ctx(settings: Settings):  # type: ignore[no-untyped-def]
    c = build_context(settings)
    c.set_router(build_router(settings, c.db, backend=FakeBackend()))
    return c


async def test_seed_to_clustered(ctx) -> None:  # type: ignore[no-untyped-def]
    res = load_seed(ctx, SEED, shift_to_now=True)
    assert res == {"total": 9, "inserted": 9, "shifted": 0}
    assert load_seed(ctx, SEED, shift_to_now=True)["inserted"] == 0  # без дублей
    stats = await pipeline_run(ctx, fetch=False)
    counts = NewsStore(ctx.db).count_by_status()
    assert set(counts) <= FINAL and sum(counts.values()) == 9
    assert stats.duplicates == counts.get("duplicate", 0) == 1
    assert stats.filtered_out == counts.get("filtered_out", 0) == 2
    assert stats.clustered == counts.get("clustered", 0) == 6
    assert stats.tagged == 6
    events = EventStore(ctx.db).load_signals(EventStore(ctx.db).list_ids())
    assert len(events) == 3 and all(e.publisher_count == 2 for e in events)
    again = await pipeline_run(ctx, fetch=False)
    assert again.tagged == again.clustered == again.extracted == 0


async def test_max_cost_stops_tagging(ctx) -> None:  # type: ignore[no-untyped-def]
    load_seed(ctx, SEED)
    stats = await pipeline_run(ctx, max_cost_rub=0, fetch=False)
    assert stats.tagged == 0
    work = pending_work(ctx)
    assert work["extracted"] == 6 and work["new"] == 0
