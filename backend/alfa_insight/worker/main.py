"""Планировщик worker на APScheduler (docs/06-ingestion-search.md §14)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from alfa_insight.appctx import AppContext, build_context
from alfa_insight.log import get_logger
from alfa_insight.worker.jobs import WorkerJobs

log = get_logger("worker.main")
MSK = "Europe/Moscow"
JOB_DEFAULTS = {"max_instances": 1, "coalesce": True, "misfire_grace_time": 60}


@dataclass
class Intervals:
    """Интервалы в секундах (тесты ускоряют их)."""

    rss_fetch: float = 15 * 60
    pipeline_tick: float = 5 * 60
    rank: float = 10 * 60
    precompute: float = 15 * 60

    @classmethod
    def from_settings(cls, app: AppContext) -> Intervals:
        return cls(rss_fetch=app.settings.ingest_rss_interval_min * 60)


def build_scheduler(
    app: AppContext, jobs: WorkerJobs | None = None, intervals: Intervals | None = None, *, daily: bool = True
) -> tuple[AsyncIOScheduler, WorkerJobs]:
    jobs = jobs or WorkerJobs(app)
    iv = intervals or Intervals.from_settings(app)
    sched = AsyncIOScheduler(job_defaults=JOB_DEFAULTS, timezone=MSK)
    for name in ("rss_fetch", "pipeline_tick", "rank", "precompute"):
        sched.add_job(getattr(jobs, name), IntervalTrigger(seconds=getattr(iv, name)), id=name, name=name)
    if daily:
        sched.add_job(jobs.macro_refresh, CronTrigger(hour=8, minute=35, timezone=MSK), id="macro_refresh")
        sched.add_job(jobs.housekeeping, CronTrigger(hour=3, minute=10, timezone=MSK), id="housekeeping")
        if app.ranking_config.rerank.enabled:
            sched.add_job(jobs.rerank, CronTrigger(hour=6, minute=20, timezone=MSK), id="rerank")
    return sched, jobs


async def startup(jobs: WorkerJobs) -> None:
    """При старте: зависшие прогоны, макро, новые PDF аналитики."""
    jobs.runner.recover_stale()
    await jobs.macro_refresh()
    await jobs.research_ingest()


async def run_worker(app: AppContext | None = None, *, stop: asyncio.Event | None = None) -> None:
    app = app or build_context()
    sched, jobs = build_scheduler(app)
    await startup(jobs)
    sched.start()
    log.info("worker_started", jobs=[j.id for j in sched.get_jobs()])
    try:
        await (stop or asyncio.Event()).wait()
    finally:
        sched.shutdown(wait=False)
        await jobs.runner.wait_all()


def start_embedded(app: AppContext) -> tuple[AsyncIOScheduler, WorkerJobs, asyncio.Task[None]]:
    """RUN_WORKER_IN_API=true: планировщик внутри lifespan API (задача старта — фоном)."""
    sched, jobs = build_scheduler(app)
    task = asyncio.get_running_loop().create_task(startup(jobs))
    sched.start()
    log.info("worker_embedded_started", jobs=[j.id for j in sched.get_jobs()])
    return sched, jobs, task
