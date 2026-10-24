"""Разнообразие выдачи: повтор главного пути влияния понижает позицию (docs/07-ranking.md §9.2)."""

from __future__ import annotations

import heapq
import json
from collections.abc import Callable, Sequence
from typing import Any

REPEAT_PENALTY = 0.55


def main_path_key(row: dict[str, Any]) -> str:
    """`channel:factor|industry` первого пути из `rankings.chain_json`; без путей — уникальный ключ события."""
    try:
        paths = json.loads(row.get("chain_json") or "{}").get("paths") or []
    except (TypeError, ValueError):
        paths = []
    if not paths:
        return f"event:{row.get('event_id')}"
    p = paths[0]
    return f"{p.get('channel')}:{p.get('factor_id') or p.get('industry_id')}"


def diversify[T](
    items: Sequence[T],
    *,
    score: Callable[[T], float],
    key: Callable[[T], str],
    penalty: float = REPEAT_PENALTY,
) -> list[T]:
    """Жадный порядок по score × penalty^(число уже выбранных с тем же ключом). Детерминирован."""
    counts: dict[str, int] = {}
    heap = [(-score(it), i, 0) for i, it in enumerate(items)]
    heapq.heapify(heap)
    out: list[T] = []
    while heap:
        _, i, seen = heapq.heappop(heap)
        k = key(items[i])
        c = counts.get(k, 0)
        if c != seen:  # штраф устарел — пересчитать и вернуть в кучу
            heapq.heappush(heap, (-score(items[i]) * penalty**c, i, c))
            continue
        counts[k] = c + 1
        out.append(items[i])
    return out


def diversify_rows(rows: Sequence[dict[str, Any]], penalty: float = REPEAT_PENALTY) -> list[dict[str, Any]]:
    return diversify(rows, score=lambda r: float(r["score"]), key=main_path_key, penalty=penalty)
