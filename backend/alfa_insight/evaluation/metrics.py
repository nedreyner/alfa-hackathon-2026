"""Метрики ранжирования и согласия разметчиков (docs/12-quality.md §2.3, §3). Чистые функции."""

from __future__ import annotations

import math
from collections.abc import Sequence


def dcg(rels: Sequence[int], k: int) -> float:
    return sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels[:k]))


def ndcg(ranked_rels: Sequence[int], k: int = 5) -> float | None:
    """None — у компании нет релевантных событий (IDCG = 0), она пропускается."""
    ideal = dcg(sorted(ranked_rels, reverse=True), k)
    return dcg(ranked_rels, k) / ideal if ideal > 0 else None


def precision_at(ranked_rels: Sequence[int], k: int = 5, min_rel: int = 2) -> float:
    return sum(1 for r in ranked_rels[:k] if r >= min_rel) / k


def recall_rel3_at(ranked_rels: Sequence[int], k: int = 5) -> float | None:
    total = sum(1 for r in ranked_rels if r == 3)
    return sum(1 for r in ranked_rels[:k] if r == 3) / total if total else None


def _ranks(values: Sequence[float]) -> list[float]:
    """Средние ранги с учётом связок."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for t in range(i, j + 1):
            ranks[order[t]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return cov / (vx * vy) if vx and vy else None


def direction_score(predicted: str, gold: str) -> float:
    """Совпадение направления; mixed против risk или opportunity — 0.5."""
    if predicted == gold:
        return 1.0
    if "mixed" in (predicted, gold):
        return 0.5
    return 0.0


def weighted_kappa(a: Sequence[int], b: Sequence[int], categories: int = 4) -> float | None:
    """Взвешенная (квадратичная) каппа Коэна для оценок 0..categories−1."""
    n = len(a)
    if n == 0 or n != len(b):
        return None
    w = [[(i - j) ** 2 / (categories - 1) ** 2 for j in range(categories)] for i in range(categories)]
    obs = [[0.0] * categories for _ in range(categories)]
    for x, y in zip(a, b, strict=True):
        obs[x][y] += 1 / n
    pa = [sum(obs[i]) for i in range(categories)]
    pb = [sum(obs[i][j] for i in range(categories)) for j in range(categories)]
    num = sum(w[i][j] * obs[i][j] for i in range(categories) for j in range(categories))
    den = sum(w[i][j] * pa[i] * pb[j] for i in range(categories) for j in range(categories))
    return 1 - num / den if den else None


def median(values: Sequence[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]
