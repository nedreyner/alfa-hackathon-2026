"""Метрики генерации на 3 событиях rel ≥ 2 каждой компании (docs/12-quality.md §4)."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from alfa_insight.agent.schemas import Insight
from alfa_insight.appctx import AppContext
from alfa_insight.evaluation import metrics as m
from alfa_insight.evaluation.dataset import Gold, default_role, eval_now, score_events, seed_events
from alfa_insight.services.insights import find_current
from alfa_insight.store.insights import InsightRow
from alfa_insight.store.runs import RunStore
from alfa_insight.text.numbers import extract_numbers

PERSONAL_PREFIXES = ("suppliers.", "buyers.", "products.", "ved.", "factor.")
VERDICT_SCORE = {"supported": 1.0, "partial": 0.5, "unsupported": 0.0, "contradicted": 0.0}


def eval_events(app: AppContext, gold: Gold, top: int = 3) -> list[tuple[str, int]]:
    """(компания, событие): лучшие по разметке события rel ≥ 2, при равенстве — по нашему скору."""
    by_seed = seed_events(app)
    out: list[tuple[str, int]] = []
    companies = sorted({c for c, _ in gold.labels})
    for cid in companies:
        cand = [(lab.relevance, by_seed[sid]) for (c, sid), lab in gold.labels.items()
                if c == cid and lab.relevance >= 2 and sid in by_seed]  # fmt: skip
        if not cand:
            continue
        ids = [e for _, e in cand]
        scores = score_events(app, cid, app.ranking.events.load_signals(ids), eval_now(app, ids))
        cand.sort(key=lambda x: (-x[0], -scores[x[1]][0]))
        out += [(cid, e) for _, e in cand[:top]]
    return out


def enqueue_missing(app: AppContext, pairs: list[tuple[str, int]]) -> int:
    runs = RunStore(app.db)
    n = 0
    for cid, eid in pairs:
        if find_current(app, cid, eid) is None and runs.active_for(cid, eid) is None:
            runs.create(kind="insight", mode="pipeline", company_id=cid, role=default_role(app, cid),
                        event_id=eid, priority="precompute")  # fmt: skip
            n += 1
    return n


def _latency_ms(app: AppContext, row: InsightRow) -> int | None:
    run = RunStore(app.db).get(row.run_id)
    if run is None or not run.started_at or not run.finished_at:
        return None
    start, end = datetime.fromisoformat(run.started_at), datetime.fromisoformat(run.finished_at)
    return int((end - start).total_seconds() * 1000)


def insight_metrics(ins: Insight, verification: dict[str, Any]) -> dict[str, Any]:
    """Показатели одного инсайта; утверждения fact и bank — по итоговому тексту."""
    types = {p: c.type for p, c in ins.claims()}
    graded = [VERDICT_SCORE.get(v["verdict"], 0.0) for v in verification.get("verdicts", [])
              if types.get(v["path"]) in ("fact", "bank")]  # fmt: skip
    numbered = [p for p, c in ins.claims() if c.type in ("fact", "bank") and extract_numbers(c.text)]
    failed_numbers = {
        p for ch in verification.get("checks", []) if ch["code"] == "numbers_match" and ch["status"] == "fail"
        for p in ch["paths"]
    }  # fmt: skip
    bank = ins.bank_view
    complete = bool(
        ins.what_happened.facts and ins.why_it_matters.summary and ins.consequences and ins.actions
        and (bank.claims if bank.available else bank.alignment == "no_data")
    )  # fmt: skip
    return {
        "grounded": sum(graded) / len(graded) if graded else None,
        "complete": complete,
        "contradiction": bool(verification.get("contradictions")),
        "personal": any(k.startswith(PERSONAL_PREFIXES) for k in ins.why_it_matters.client_features_used),
        "numbers": (len(numbered), len([p for p in numbered if p in failed_numbers])),
        "needs_review": ins.status == "needs_review",
    }


def evaluate_generation(app: AppContext, pairs: list[tuple[str, int]]) -> dict[str, Any]:
    rows = [r for r in (find_current(app, c, e) for c, e in pairs) if r is not None]
    per = []
    latencies, costs = [], []
    for r in rows:
        ins = Insight.model_validate(r.payload)
        per.append(insight_metrics(ins, r.verification))
        lat = _latency_ms(app, r)
        if lat is not None:
            latencies.append(lat)
        costs.append(r.cost_rub)
    n = len(per)

    def share(key: str) -> float | None:
        return round(sum(1 for x in per if x[key]) / n, 4) if n else None

    grounded = [x["grounded"] for x in per if x["grounded"] is not None]
    num_total = sum(x["numbers"][0] for x in per)
    num_failed = sum(x["numbers"][1] for x in per)
    return {
        "insights": n,
        "planned": len(pairs),
        "grounded_share_llm": round(sum(grounded) / len(grounded), 4) if grounded else None,
        "completeness": share("complete"),
        "contradiction_rate": share("contradiction"),
        "personalization_rate": share("personal"),
        "numbers_match_rate": round(1 - num_failed / num_total, 4) if num_total else None,
        "needs_review_share": share("needs_review"),
        "latency_ms": {"p50": m.percentile(latencies, 0.5), "p95": m.percentile(latencies, 0.95)},
        "cost_rub_mean": round(sum(costs) / len(costs), 4) if costs else None,
    }


def sample_claims(
    app: AppContext, pairs: list[tuple[str, int]], n: int, seed: int = 11
) -> list[dict[str, str]]:
    """Случайные утверждения fact и bank для ручной проверки обоснованности (`grounding_check.csv`)."""
    items: list[dict[str, str]] = []
    for cid, eid in pairs:
        row = find_current(app, cid, eid)
        if row is None:
            continue
        ins = Insight.model_validate(row.payload)
        verdicts = {v["path"]: v["verdict"] for v in row.verification.get("verdicts", [])}
        src = {s.id: s for s in ins.sources}
        for path, c in ins.claims():
            if c.type not in ("fact", "bank"):
                continue
            items.append({
                "insight_id": row.id, "path": path, "type": c.type, "text": c.text,
                "sources": " | ".join(f"{src[r].title} ({src[r].publisher or src[r].kind})" for r in c.refs if r in src),
                "llm_verdict": verdicts.get(path, ""), "human_verdict": "",
            })  # fmt: skip
    random.Random(seed).shuffle(items)
    return items[:n]
