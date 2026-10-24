"""Метрики ранжирования на размеченном наборе и базовые варианты (docs/12-quality.md §3)."""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any

from alfa_insight.appctx import AppContext
from alfa_insight.evaluation import metrics as m
from alfa_insight.evaluation.dataset import VARIANTS, Gold, Variant, eval_now, score_events, seed_events

RANDOM_SHUFFLES = 100
K = 5


def _company_metrics(items: list[tuple[float, str, int, str]]) -> dict[str, float | None]:
    """items: (скор, наше направление, rel, направление разметки)."""
    ranked = sorted(items, key=lambda x: -x[0])
    rels = [x[2] for x in ranked]
    dirs = [m.direction_score(x[1], x[3]) for x in items if x[2] >= 2 and x[3] != "none"]
    return {
        "ndcg@5": m.ndcg(rels, K),
        "p@5": m.precision_at(rels, K),
        "recall_rel3@5": m.recall_rel3_at(rels, K),
        "spearman": m.spearman([x[0] for x in items], [float(x[2]) for x in items]),
        "direction_acc": sum(dirs) / len(dirs) if dirs else None,
    }


def _mean(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def _aggregate(per_company: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    keys = ["ndcg@5", "p@5", "recall_rel3@5", "spearman", "direction_acc"]
    return {k: _mean([pc[k] for pc in per_company.values()]) for k in keys}


def _random_baseline(by_company: dict[str, list[int]]) -> dict[str, float | None]:
    rng = random.Random(7)
    ndcgs: list[float | None] = []
    ps: list[float | None] = []
    for rels in by_company.values():
        for _ in range(RANDOM_SHUFFLES):
            shuffled = rels[:]
            rng.shuffle(shuffled)
            ndcgs.append(m.ndcg(shuffled, K))
            ps.append(m.precision_at(shuffled, K))
    return {"ndcg@5": _mean(ndcgs), "p@5": _mean(ps)}


def collect(
    app: AppContext, gold: Gold, variant: Variant = "ours", channel_weights: dict[str, float] | None = None
) -> tuple[dict[str, list[tuple[float, str, int, str]]], int]:
    """Скоры размеченных событий по компаниям; второе значение — число суждений без события в базе."""
    by_seed = seed_events(app)
    pairs = defaultdict(list)
    missing = 0
    for (cid, sid), label in gold.labels.items():
        if sid not in by_seed:
            missing += 1
            continue
        pairs[cid].append((by_seed[sid], label))
    ids = sorted({eid for xs in pairs.values() for eid, _ in xs})
    if not ids:
        return {}, missing
    signals = {s.event_id: s for s in app.ranking.events.load_signals(ids)}
    now = eval_now(app, ids)
    out: dict[str, list[tuple[float, str, int, str]]] = {}
    for cid, xs in pairs.items():
        scores = score_events(app, cid, [signals[e] for e, _ in xs], now, variant, channel_weights)
        out[cid] = [(scores[e][0], scores[e][1], lab.relevance, lab.direction) for e, lab in xs]
    return out, missing


def evaluate_ranking(app: AppContext, gold: Gold, *, baselines: bool = True) -> dict[str, Any]:
    data, missing = collect(app, gold)
    per_company = {cid: _company_metrics(items) for cid, items in sorted(data.items())}
    result: dict[str, Any] = {
        **_aggregate(per_company),
        "per_company": per_company,
        "missing_events": missing,
    }
    medians: dict[str, float | None] = {}
    by_rel: dict[int, list[float]] = defaultdict(list)
    for items in data.values():
        for score, _d, rel, _gd in items:
            by_rel[rel].append(score)
    for rel in range(4):
        med = m.median(by_rel.get(rel, []))
        medians[str(rel)] = round(med, 4) if med is not None else None
    result["score_medians_by_rel"] = medians
    if baselines:
        bl: dict[str, Any] = {"random": _random_baseline({c: [x[2] for x in xs] for c, xs in data.items()})}
        for variant in VARIANTS[1:]:
            vdata, _ = collect(app, gold, variant)
            bl[variant] = _aggregate({c: _company_metrics(xs) for c, xs in vdata.items()})
        result["baselines"] = bl
    return result
