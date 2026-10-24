"""Прогоны агента: интерактивный запуск, очередь прекомпьюта, таймауты, коды ошибок (docs/08-agent.md §1.3, §17)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from alfa_insight.agent.context import AgentContext, AgentLimits
from alfa_insight.agent.intake import AnalyzeInput
from alfa_insight.agent.runtime import run_agent
from alfa_insight.appctx import AppContext
from alfa_insight.errors import (
    AppError,
    BudgetExceeded,
    Busy,
    LLMInvalidOutput,
    LLMUnavailable,
    NotFoundError,
)
from alfa_insight.log import get_logger
from alfa_insight.services.insights import find_current
from alfa_insight.store.events import EventStore
from alfa_insight.store.runs import RunRow, RunStore

log = get_logger("services.jobs")

QUEUE_TICK_LIMIT = 10
QUEUE_CONCURRENCY = 2
CHAT_TIMEOUT_S = 30
ERROR_MESSAGES = {
    "llm_unavailable": "Сервис аналитики временно недоступен, попробуйте позже",
    "budget_exhausted": "Дневной лимит аналитики исчерпан, показываем готовые разборы",
    "invalid_output": "Не удалось подготовить разбор, попробуйте ещё раз",
    "fetch_failed": "Сайт не отдал страницу. Вставьте текст новости",
    "unsupported_content": "Не удалось извлечь текст статьи. Вставьте текст вручную",
    "blocked_url": "Этот адрес нельзя загрузить",
    "timeout": "Разбор занял слишком много времени, попробуйте ещё раз",
    "interrupted": "Разбор прерван, запустите заново",
    "internal": "Внутренняя ошибка",
}


def error_code(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, BudgetExceeded):
        return "budget_exhausted"
    if isinstance(exc, LLMUnavailable):
        return "llm_unavailable"
    if isinstance(exc, LLMInvalidOutput):
        return "invalid_output"
    if isinstance(exc, AppError) and exc.code in ERROR_MESSAGES:
        return exc.code
    return "internal"


@dataclass
class StartResult:
    status: Literal["ready", "started", "running"]
    insight_id: str | None = None
    run_id: str | None = None


@dataclass
class JobRunner:
    """Один на процесс: семафор интерактивных прогонов и ссылки на фоновые задачи."""

    app: AppContext
    _active: int = 0
    _tasks: set[asyncio.Task[RunRow]] = field(default_factory=set)
    _sem: asyncio.Semaphore | None = None
    fetch_options: dict[str, Any] = field(default_factory=dict)  # тесты фичи B: transport, resolver

    @property
    def runs(self) -> RunStore:
        return RunStore(self.app.db)

    def _semaphore(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.app.settings.agent_max_concurrent_runs)
        return self._sem

    def timeout_for(self, kind: str) -> float:
        return CHAT_TIMEOUT_S if kind == "chat" else self.app.settings.agent_run_timeout_s

    def recover_stale(self) -> int:
        n = self.runs.recover_stale(older_than_s=2 * self.app.settings.agent_run_timeout_s)
        if n:
            log.warning("runs_interrupted", count=n)
        return n

    # ── интерактивный запуск ──
    def start_interactive(
        self, company_id: str, role: str, event_id: int, *, session_id: str | None = None
    ) -> StartResult:
        """POST /api/events/{id}/insight: готовый → ready, идущий → running, иначе новый прогон."""
        ev = EventStore(self.app.db).get(event_id)
        if ev is None or (ev.visibility == "private" and ev.owner_company_id != company_id):
            raise NotFoundError("Событие не найдено", {"event_id": event_id})
        ready = find_current(self.app, company_id, event_id)
        if ready is not None:
            return StartResult(status="ready", insight_id=ready.id)
        active = self.runs.active_for(company_id, event_id, "insight")
        if active is not None:
            return StartResult(status="running", run_id=active.id)
        if self._active >= self.app.settings.agent_max_concurrent_runs:
            raise Busy("Сейчас идёт много разборов, попробуйте через минуту")
        run_id = self.runs.create(
            kind="insight", mode="pipeline", company_id=company_id, role=role, event_id=event_id,
            session_id=session_id, priority="interactive",
        )  # fmt: skip
        self.spawn(run_id)
        return StartResult(status="started", run_id=run_id)

    def start_analyze(
        self, company_id: str, role: str, inp: AnalyzeInput, *, session_id: str | None = None
    ) -> str:
        """POST /api/analyze: прогон kind=analyze, mode=agentic; событие появится по ходу intake."""
        if self._active >= self.app.settings.agent_max_concurrent_runs:
            raise Busy("Сейчас идёт много разборов, попробуйте через минуту")
        run_id = self.runs.create(
            kind="analyze", mode="agentic", company_id=company_id, role=role, session_id=session_id,
            priority="interactive", input=inp.model_dump(mode="json", exclude_none=True),
        )  # fmt: skip
        self.spawn(run_id)
        return run_id

    def spawn(self, run_id: str) -> asyncio.Task[RunRow]:
        task = asyncio.get_running_loop().create_task(self.execute(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    # ── выполнение ──
    async def execute(self, run_id: str) -> RunRow:
        """queued → running → succeeded | failed; любые ошибки записываются в прогон и трассу."""
        runs = self.runs
        run = runs.get(run_id)
        if run is None:
            raise NotFoundError("Прогон не найден", {"run_id": run_id})
        if run.status == "queued" and not runs.start(run_id):
            return runs.get(run_id)  # type: ignore[return-value]
        self._active += 1
        try:
            async with self._semaphore():
                profile = self.app.profiles.get(run.company_id)
                ctx = AgentContext.create(
                    self.app, run_id=run.id, kind=run.kind, mode=run.mode, profile=profile,  # type: ignore[arg-type]
                    role=(run.role or "cfo"), event_id=run.event_id, priority=run.priority,  # type: ignore[arg-type]
                    limits=AgentLimits.from_app(self.app).model_copy(update={"timeout_s": int(self.timeout_for(run.kind))}),
                )  # fmt: skip
                analyze = AnalyzeInput.model_validate(run.input) if run.kind == "analyze" else None
                await asyncio.wait_for(
                    run_agent(ctx, analyze=analyze, fetch_options=self.fetch_options),
                    timeout=self.timeout_for(run.kind),
                )
        except Exception as exc:
            code = error_code(exc)
            if code == "internal":
                log.exception("run_failed", run_id=run_id)
            else:
                log.warning("run_failed", run_id=run_id, code=code, error=str(exc)[:200])
            runs.fail(run_id, code, ERROR_MESSAGES[code])
            runs.add_trace(
                run_id, runs.last_seq(run_id) + 1, type="run.failed", phase="finalize",
                title=ERROR_MESSAGES[code], status="error", payload={"error_code": code, "message": str(exc)[:300]},
            )  # fmt: skip
            if isinstance(exc, BudgetExceeded) and exc.scope in ("day", "reserve"):
                raise
        finally:
            self._active -= 1
        return runs.get(run_id)  # type: ignore[return-value]

    async def process_queue(
        self, *, limit: int = QUEUE_TICK_LIMIT, concurrency: int = QUEUE_CONCURRENCY
    ) -> int:
        """Очередь прекомпьюта: до `limit` прогонов, `concurrency` параллельно; стоп на дневном бюджете."""
        done = 0
        stop = asyncio.Event()

        async def worker() -> None:
            nonlocal done
            while not stop.is_set() and done < limit:
                run = self.runs.claim_next(("precompute", "background"))
                if run is None:
                    return
                done += 1
                try:
                    await self.execute(run.id)
                except BudgetExceeded:
                    stop.set()

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        return done

    async def wait_all(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
