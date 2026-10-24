from __future__ import annotations

import asyncio

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
    assert all(r.priority == "precompute" and r.role == role for r in pending)

    done = asyncio.run(JobRunner(app).process_queue(limit=2))
    assert done == 2
    statuses = runs.count_by_status()
    assert statuses.get("succeeded") == 2, statuses
    assert sum(InsightStore(app.db).count_by_status().values()) == 2
    # повтор: готовые и стоящие в очереди пары не дублируются
    assert enqueue_precompute(app, companies=["SYN-DEMO-02", "SYN-DEMO-01"], top_k=2) == 0
