"""Трасса прогона: упорядоченные события для пользователя и аудита (docs/08-agent.md §11)."""

from __future__ import annotations

import threading
import time
from typing import Any

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.llm.types import LLMCallRecord
from alfa_insight.store.runs import RunStore

TASK_TITLES = {
    "tagging": "разметка",
    "tagging_interactive": "разметка",
    "agent": "агент",
    "draft": "черновик",
    "revise": "доработка",
    "verify": "проверка",
    "chat": "ответ",
    "research_extract": "аналитика",
}
MODEL_TITLES = {
    "deepseek": "DeepSeek-V4.1-Flash",
    "glm": "GLM-5.3-Flash",
    "kimi": "Kimi-K2.6",
    "gemma": "Gemma 4",
    "qwen_text": "Qwen3.6",
    "qwen_vl": "Qwen3-VL",
    "fake": "FakeLLM",
}


class TraceWriter:
    """Каждая запись — отдельная короткая транзакция; seq монотонно растёт внутри прогона."""

    def __init__(self, db: SqliteDB, run_id: str):
        self.store = RunStore(db)
        self.run_id = run_id
        self._lock = threading.Lock()
        self._seq = self.store.last_seq(run_id)
        self._started = time.monotonic()
        self._phase = "plan"

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._started) * 1000)

    def emit(
        self,
        type: str,
        phase: str | None,
        title: str,
        *,
        status: str = "ok",
        payload: dict[str, Any] | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_rub: float | None = None,
        latency_ms: int | None = None,
    ) -> int:
        with self._lock:
            self._seq += 1
            seq = self._seq
            self.store.add_trace(
                self.run_id,
                seq,
                type=type,
                phase=phase or self._phase,
                title=title,
                status=status,
                payload=payload or {},
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_rub=cost_rub,
                latency_ms=latency_ms,
            )
        return seq

    def phase(self, name: str, title: str) -> None:
        self._phase = name
        self.emit("phase.started", name, title)

    def on_llm_call(self, rec: LLMCallRecord) -> None:
        """Слушатель роутера: событие llm.call для вызовов этого прогона."""
        if rec.run_id != self.run_id:
            return
        model = MODEL_TITLES.get(rec.model, rec.model)
        task = TASK_TITLES.get(rec.task, rec.task)
        suffix = " · из кеша" if rec.cached else (" · запасная модель" if rec.fallback_model_used else "")
        self.emit(
            "llm.call",
            None,
            f"{model} · {task}{suffix}",
            status="ok" if rec.status == "ok" else ("warn" if rec.status == "invalid_output" else "error"),
            payload={
                "task": rec.task,
                "model": rec.model,
                "tokens_in": rec.tokens_in,
                "tokens_out": rec.tokens_out,
                "cost_rub": rec.cost_rub,
                "cached": rec.cached,
                "fallback_model_used": rec.fallback_model_used,
                "status": rec.status,
            },
            model=rec.model,
            tokens_in=rec.tokens_in,
            tokens_out=rec.tokens_out,
            cost_rub=rec.cost_rub,
            latency_ms=rec.latency_ms,
        )
