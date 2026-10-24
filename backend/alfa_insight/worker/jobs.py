"""Задачи worker (docs/06-ingestion-search.md §14). Ошибка задачи логируется и не роняет процесс."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
from collections.abc import Awaitable, Callable
from typing import Any

from alfa_insight.appctx import AppContext
from alfa_insight.errors import BudgetExceeded
from alfa_insight.log import get_logger
from alfa_insight.services.jobs import JobRunner, enqueue_precompute

log = get_logger("worker.jobs")

JobFn = Callable[[], Awaitable[Any]]


def safe_job(name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def deco(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kw: Any) -> Any:
            try:
                result = await fn(*args, **kw)
                log.info("job_done", job=name, result=result)
                return result
            except BudgetExceeded as exc:
                log.warning("job_budget_stop", job=name, scope=exc.scope)
            except Exception:
                log.exception("job_failed", job=name)
            return None

        return wrapper

    return deco


class WorkerJobs:
    """Набор задач над одним AppContext; счётчики — для тестов и /api/meta."""

    def __init__(self, app: AppContext, runner: JobRunner | None = None):
        self.app = app
        self.runner = runner or JobRunner(app)
        self.runs: dict[str, int] = {}
        self._rank_needed = False

    def _count(self, name: str) -> None:
        self.runs[name] = self.runs.get(name, 0) + 1

    @safe_job("rss_fetch")
    async def rss_fetch(self) -> int:
        self._count("rss_fetch")
        if not self.app.settings.ingest_enabled:
            return 0
        from alfa_insight.ingest.rss import collect_rss
        from alfa_insight.store.news import NewsStore

        s = self.app.settings
        results = await collect_rss(
            self.app.sources,
            NewsStore(self.app.db),
            self.app.kv,
            ingest_geo=s.ingest_geo,
            max_age_days=s.rss_max_age_days,
        )
        return sum(r.items_new for r in results)

    @safe_job("pipeline_tick")
    async def pipeline_tick(self) -> dict[str, Any]:
        self._count("pipeline_tick")
        from alfa_insight.ingest.pipeline import pipeline_tick

        stats = await pipeline_tick(self.app, max_cost_rub=self.app.settings.pipeline_tick_max_cost_rub)
        if stats.clustered:
            await self.rank()  # сразу после тика с новыми событиями
        return stats.model_dump()

    @safe_job("rank")
    async def rank(self) -> int:
        self._count("rank")
        return await asyncio.to_thread(self.app.ranking.rank_all)

    @safe_job("rerank")
    async def rerank(self) -> int:
        """LLM-переранжирование топа компаний прекомпьюта (07-ranking.md §10); выключено флагом конфига."""
        self._count("rerank")
        if not self.app.ranking_config.rerank.enabled:
            return 0
        from alfa_insight.ranking.rerank import rerank_company
        from alfa_insight.services.jobs import precompute_companies

        n = 0
        for company_id in precompute_companies(self.app):
            n += await rerank_company(self.app, company_id)
        return n

    @safe_job("precompute")
    async def precompute(self) -> int:
        self._count("precompute")
        if not self.app.settings.precompute_enabled:
            return 0
        await asyncio.to_thread(enqueue_precompute, self.app)
        return await self.runner.process_queue()

    @safe_job("macro_refresh")
    async def macro_refresh(self) -> dict[str, int]:
        self._count("macro_refresh")
        from alfa_insight.ingest.macro import load_snapshot, refresh_macro
        from alfa_insight.store.macro import MacroStore

        store = MacroStore(self.app.db)
        try:
            return await refresh_macro(store)
        except Exception as exc:
            log.warning("macro_refresh_failed", error=str(exc)[:200])
            return {"snapshot": load_snapshot(store, self.app.settings.seed_dir / "macro.json")}

    @safe_job("research_ingest")
    async def research_ingest(self) -> dict[str, Any] | None:
        self._count("research_ingest")
        from alfa_insight.ingest.research.pipeline import ingest_research

        directory = self.app.settings.raw_dir / "research"
        if not directory.exists() or not any(directory.glob("*.pdf")):
            return None
        stats = await ingest_research(self.app, directory, max_cost_rub=self.app.settings.init_max_cost_rub)
        return dataclasses.asdict(stats)

    @safe_job("housekeeping")
    async def housekeeping(self) -> dict[str, int]:
        self._count("housekeeping")
        stale = self.runner.recover_stale()
        await asyncio.to_thread(self.app.db.execute, "PRAGMA optimize")
        return {"stale_runs": stale}
