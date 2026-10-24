"""Токен-бакеты в памяти процесса (docs/09-api.md §7). Ключ — sid сессии, для входа — IP."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from alfa_insight.errors import RateLimited

LIMITS: dict[str, list[tuple[int, float]]] = {  # имя → [(ёмкость, период, с)]
    "analyze": [(6, 60), (60, 86400)],
    "generate": [(10, 60)],
    "chat": [(15, 60), (200, 86400)],
    "session": [(20, 60)],
    "write": [(60, 60)],
}


@dataclass
class Bucket:
    capacity: int
    period: float
    tokens: float
    updated: float

    def take(self, now: float) -> float:
        """0 — токен взят, иначе через сколько секунд появится."""
        rate = self.capacity / self.period
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * rate)
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return 0.0
        return (1 - self.tokens) / rate


class RateLimiter:
    def __init__(
        self,
        limits: dict[str, list[tuple[int, float]]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limits = limits or LIMITS
        self.clock = clock
        self._buckets: dict[tuple[str, str, int], Bucket] = {}
        self._lock = threading.Lock()

    def hit(self, name: str, key: str) -> None:
        now = self.clock()
        with self._lock:
            waits = []
            for i, (cap, period) in enumerate(self.limits.get(name, [])):
                b = self._buckets.get((name, key, i))
                if b is None:
                    b = self._buckets[(name, key, i)] = Bucket(cap, period, float(cap), now)
                waits.append(b.take(now))
            wait = max(waits, default=0.0)
        if wait > 0:
            raise RateLimited("Слишком много запросов, попробуйте чуть позже", retry_after_s=wait)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
