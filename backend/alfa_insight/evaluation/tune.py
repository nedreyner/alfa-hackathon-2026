"""`alfa eval tune`: перебор весов каналов по разметке и обратной связи (docs/12-quality.md §7)."""

from __future__ import annotations

import itertools
from typing import Any

from alfa_insight.appctx import AppContext
from alfa_insight.evaluation import metrics as m
from alfa_insight.evaluation.dataset import Gold, Label
from alfa_insight.evaluation.ranking_eval import collect

LAMBDA = 0.5
CHANNELS = ("own", "supply", "demand", "factor")


def with_feedback(app: AppContext, gold: Gold) -> Gold:
    """Онлайн-обратная связь как дополнительная разметка: 👍 → rel 2, 👎 «не про нас» → rel 0."""
    rows = app.db.query(
        "SELECT f.company_id, n.external_id AS seed_id, f.useful, f.reason FROM feedback f "
        "JOIN insights i ON i.id = f.insight_id JOIN events e ON e.id = i.event_id "
        "JOIN news n ON n.id = e.lead_news_id WHERE n.origin = 'seed'"
    )
    labels = dict(gold.labels)
    for r in rows:
        key = (r["company_id"], r["seed_id"])
        if key in labels:
            continue
        if r["useful"]:
            labels[key] = Label(key[0], key[1], 2, "mixed", "feedback")
        elif r["reason"] == "not_relevant":
            labels[key] = Label(key[0], key[1], 0, "none", "feedback")
    return Gold(labels, gold.source, gold.kappa, gold.overlap)


def _objective(app: AppContext, gold: Gold, weights: dict[str, float], base: dict[str, float]) -> float:
    data, _ = collect(app, gold, channel_weights=weights)
    vals = [m.ndcg([x[2] for x in sorted(xs, key=lambda x: -x[0])], 5) for xs in data.values()]
    nd = [v for v in vals if v is not None]
    mean = sum(nd) / len(nd) if nd else 0.0
    return mean - LAMBDA * sum((weights[c] - base[c]) ** 2 for c in CHANNELS)


def tune(app: AppContext, gold: Gold, step: float = 0.25) -> dict[str, Any]:
    base = {c: float(app.ranking_config.channel_weights[c]) for c in CHANNELS}  # type: ignore[index]
    n = round(1.0 / step)
    grid = [round(0.5 + i * step, 4) for i in range(n + 1)]
    best, best_val = base, _objective(app, gold, base, base)
    start_val = best_val
    for combo in itertools.product(grid, repeat=len(CHANNELS)):
        weights = dict(zip(CHANNELS, combo, strict=True))
        val = _objective(app, gold, weights, base)
        if val > best_val + 1e-9:
            best, best_val = weights, val
    return {"base": base, "best": best, "objective_base": round(start_val, 4), "objective_best": round(best_val, 4),
            "grid": grid, "lambda": LAMBDA}  # fmt: skip
