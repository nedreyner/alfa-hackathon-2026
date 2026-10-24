"""Состав seed-набора (docs/06-ingestion-search.md §10) по разметке куратора и после конвейера на FakeLLM."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from alfa_insight.appctx import build_context
from alfa_insight.config_models import DemoConfig, load_yaml
from alfa_insight.ingest.pipeline import pipeline_run
from alfa_insight.ingest.seed import load_seed, read_seed
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.settings import Settings
from alfa_insight.store.events import EventStore

ROOT = Path(__file__).resolve().parents[3]
SEED = ROOT / "data" / "seed" / "news.jsonl"


def test_curator_composition() -> None:
    items = read_seed(SEED)
    demo = load_yaml(ROOT / "config" / "demo.yaml", DemoConfig)
    relevant = Counter(i.expect_relevant for i in items)
    assert relevant[True] >= 150 and relevant[False] >= 10
    stories = Counter(i.story for i in items if i.story)
    for company in demo.ids():
        assert stories[company] >= 3, company
    tests = [i for i in items if i.synthetic_test]
    assert len(tests) == 2 and all(i.source_id == "test" for i in tests)
    assert len({i.seed_id for i in items}) == len(items)
    assert all(len(i.body or "") <= 3000 for i in items)


async def test_events_from_two_publishers(settings: Settings) -> None:
    ctx = build_context(settings)
    ctx.set_router(build_router(settings, ctx.db, backend=FakeBackend()))
    load_seed(ctx, SEED, shift_to_now=True)
    await pipeline_run(ctx, fetch=False)
    events = EventStore(ctx.db).load_signals(EventStore(ctx.db).list_ids())
    multi = [e for e in events if e.publisher_count >= 2]
    assert len(multi) >= 3
    flagged = ctx.db.scalar("SELECT count(*) FROM news WHERE source_id = 'test' AND injection_flags != '[]'")
    assert flagged == 2
