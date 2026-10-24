from __future__ import annotations

import asyncio

import pytest

from alfa_insight.appctx import build_context
from alfa_insight.services.jobs import JobRunner, enqueue_precompute, precompute_companies
from alfa_insight.settings import Settings
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.store.runs import RunStore
from alfa_insight.worker.jobs import WorkerJobs
from alfa_insight.worker.main import Intervals, build_scheduler, start_embedded


def test_scheduler_runs_jobs(settings: Settings) -> None:
    settings.ingest_enabled = False
    settings.precompute_enabled = False
    app = build_context(settings)

    async def go() -> WorkerJobs:
        sched, jobs = build_scheduler(app, intervals=Intervals(0.15, 0.15, 0.15, 0.15), daily=False)
        sched.start()
        await asyncio.sleep(0.8)
        sched.shutdown(wait=False)
        return jobs

    jobs = asyncio.run(go())
    for name in ("rss_fetch", "pipeline_tick", "rank", "precompute"):
        assert jobs.runs.get(name, 0) >= 2, (
            name,
            jobs.runs,
        )  # ошибки задач (нет DuckDB) не роняют планировщик


def test_embedded_start(settings: Settings) -> None:
    settings.ingest_enabled = False
    app = build_context(settings)

    async def go() -> list[str]:
        sched, jobs, task = start_embedded(app)
        await task
        ids = [j.id for j in sched.get_jobs()]
        sched.shutdown(wait=False)
        assert jobs.runs.get("macro_refresh") == 1 and jobs.runs.get("research_ingest") == 1
        return ids

    assert {"rss_fetch", "pipeline_tick", "rank", "precompute", "macro_refresh", "housekeeping"} <= set(
        asyncio.run(go())
    )


def test_precompute_selection(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    app.ranking.rank_all()
    demo = precompute_companies(app, "demo")
    assert demo == app.demo.ids() and precompute_companies(app, "SYN-DEMO-02, SYN-DEMO-01") == [
        "SYN-DEMO-02",
        "SYN-DEMO-01",
    ]
    assert precompute_companies(app, "all")[: len(demo)] == demo

    role = next(c.default_role for c in app.demo.companies if c.company_id == "SYN-DEMO-02")
    top = RankingStore(app.db).top("SYN-DEMO-02", role, min_score=app.demo.precompute.min_score, limit=2)
    assert top, "у демо-компании нет событий выше порога"
    app.db.execute("UPDATE events SET injection_suspected = 1 WHERE id = ?", (top[0]["event_id"],))

    queued = enqueue_precompute(app, companies=["SYN-DEMO-02", "SYN-DEMO-01"], top_k=2)
    runs = RunStore(app.db)
    pending = [r for r in runs.list_for_company("SYN-DEMO-02", "insight") if r.status == "queued"]
    assert queued >= 2 and top[0]["event_id"] not in {r.event_id for r in pending}
    assert all(r.priority == "precompute" for r in pending)
    # top-K — в роли по умолчанию; пункты брифингов демо-компании — в ролях брифингов
    assert top[1]["event_id"] in {r.event_id for r in pending if r.role == role}
    assert {r.role for r in pending} <= {"cfo", "treasurer", "owner"}

    done = asyncio.run(JobRunner(app).process_queue(limit=2))
    assert done == 2
    statuses = runs.count_by_status()
    assert statuses.get("succeeded") == 2, statuses
    assert sum(InsightStore(app.db).count_by_status().values()) == 2
    # повтор: готовые и стоящие в очереди пары не дублируются
    # (брифинг после готовых инсайтов может сдвинуться и добавить новое событие — это не дубль)
    enqueue_precompute(app, companies=["SYN-DEMO-02", "SYN-DEMO-01"], top_k=2)
    pairs = [
        (r.company_id, r.event_id)
        for c in ("SYN-DEMO-02", "SYN-DEMO-01")
        for r in runs.list_for_company(c, "insight")
    ]
    assert len(pairs) == len(set(pairs))


def test_rerank_applies_and_survives_rerank_all(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    from alfa_insight.ranking.rerank import judgments, kv_key, multiplier, rerank_company
    from alfa_insight.store.events import EventStore

    app = seeded_ctx
    app.ranking_config.rerank.enabled = True
    app.ranking.rank_company("SYN-DEMO-02")
    ranks = RankingStore(app.db)
    top = ranks.top("SYN-DEMO-02", "cfo", limit=3)
    victim = top[0]["event_id"]
    ev = EventStore(app.db).get(victim)
    app.db.execute("UPDATE events SET title = ? WHERE id = ?", (f"{ev.title} [[IRRELEVANT]]", victim))  # type: ignore[union-attr]
    before = {r["event_id"]: r["score"] for r in top}

    assert asyncio.run(rerank_company(app, "SYN-DEMO-02")) > 0
    profile = app.profiles.get("SYN-DEMO-02")
    got = judgments(app.kv, "SYN-DEMO-02", profile.profile_version)
    assert got[victim] == 0 and got[top[1]["event_id"]] == 2
    alpha = app.ranking_config.rerank.alpha
    row = ranks.get("SYN-DEMO-02", victim, "cfo")
    assert (
        row["score"] == pytest.approx(before[victim] * multiplier(0, alpha), rel=1e-3)
        and row["rerank_score"] == 0
    )
    app.ranking.rank_all()  # пересчёт не теряет оценки
    assert ranks.get("SYN-DEMO-02", victim, "cfo")["score"] == pytest.approx(
        before[victim] * multiplier(0, alpha), rel=1e-3
    )
    # выключенный флаг — скор без поправки
    app.ranking_config.rerank.enabled = False
    app.ranking.rank_company("SYN-DEMO-02")
    assert ranks.get("SYN-DEMO-02", victim, "cfo")["score"] == pytest.approx(before[victim], rel=1e-3)
    assert app.kv.get(kv_key("SYN-DEMO-02"))["profile_version"] == profile.profile_version
