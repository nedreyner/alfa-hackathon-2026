from __future__ import annotations

from alfa_insight.evaluation.dataset import POOL_RANDOM, POOL_TOP, Label, build_pool, gold_labels
from alfa_insight.evaluation.ranking_eval import evaluate_ranking

COMPANIES = ["SYN-DEMO-01", "SYN-DEMO-02"]


def test_pool_and_ranking_eval(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    pool = build_pool(app, COMPANIES)
    assert len(pool) == len(COMPANIES) * (POOL_TOP + POOL_RANDOM)
    assert build_pool(app, COMPANIES) == pool  # детерминированно
    # «разметка»: топ пула — 3, случайные — 0; цепная реакция должна обыграть случайный порядок
    labels = [
        Label(r["company_id"], r["seed_id"], 3 if r["origin"] == "top" else 0,
              "risk" if r["origin"] == "top" else "none", "human:test")
        for r in pool
    ]  # fmt: skip
    res = evaluate_ranking(app, gold_labels(labels))
    assert res["missing_events"] == 0 and set(res["per_company"]) == set(COMPANIES)
    assert res["ndcg@5"] == 1.0 and res["ndcg@5"] > res["baselines"]["random"]["ndcg@5"]
    assert set(res["baselines"]) == {"random", "industry_only", "no_payments"}
    assert res["score_medians_by_rel"]["3"] >= res["score_medians_by_rel"]["0"]
