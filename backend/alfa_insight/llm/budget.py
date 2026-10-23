"""Суточный бюджет и лимит на прогон (docs/04-llm.md §7)."""

from __future__ import annotations

import math
import threading
import time
from typing import Literal

from alfa_insight.errors import BudgetExceeded
from alfa_insight.llm.types import Priority
from alfa_insight.store.llm import LLMStore
from alfa_insight.timeutil import budget_day

BudgetMode = Literal["normal", "economy", "exhausted"]
SPENT_TTL_S = 5.0


def estimate_cost(text_chars: int, max_tokens: int, p_in: float, p_out: float) -> float:
    """Консервативная оценка до вызова: вход ≈ символы / 3, выход ≈ половина лимита."""
    tokens_in = math.ceil(text_chars / 3)
    tokens_out = 0.5 * max_tokens
    return (tokens_in * p_in + tokens_out * p_out) / 1e6


class BudgetGuard:
    def __init__(
        self,
        store: LLMStore,
        *,
        daily_limit_rub: float,
        interactive_reserve_rub: float,
        max_run_cost_rub: float,
        tz: str = "Europe/Moscow",
    ):
        self.store = store
        self.limit = daily_limit_rub
        self.reserve = interactive_reserve_rub
        self.max_run = max_run_cost_rub
        self.tz = tz
        self._spent_cache: tuple[str, float, float] | None = None  # (day, value, ts)
        self._lock = threading.Lock()

    def today(self) -> str:
        return budget_day(tz=self.tz).isoformat()

    def spent(self) -> float:
        day = self.today()
        with self._lock:
            cached = self._spent_cache
            if cached and cached[0] == day and time.monotonic() - cached[2] < SPENT_TTL_S:
                return cached[1]
            value = self.store.spent(day)
            self._spent_cache = (day, value, time.monotonic())
            return value

    def invalidate(self) -> None:
        with self._lock:
            self._spent_cache = None

    def mode(self) -> BudgetMode:
        spent = self.spent()
        if spent < self.limit - self.reserve:
            return "normal"
        if spent < self.limit:
            return "economy"
        return "exhausted"

    def remaining(self) -> float:
        return max(0.0, self.limit - self.spent())

    def check(self, priority: Priority, est_rub: float, run_id: str | None = None) -> None:
        spent = self.spent()
        if priority == "interactive":
            if spent + est_rub > self.limit:
                raise BudgetExceeded("day", "Суточный бюджет LLM исчерпан")
        elif spent + est_rub > self.limit - self.reserve:
            raise BudgetExceeded("reserve", "Остаток бюджета зарезервирован под интерактивные запросы")
        if run_id is not None and self.store.run_cost(run_id) + est_rub > self.max_run:
            raise BudgetExceeded("run", "Превышен лимит стоимости прогона")
