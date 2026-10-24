from __future__ import annotations

import math

import pytest

from alfa_insight.evaluation import metrics as m
from alfa_insight.evaluation.dataset import Label, gold_labels


def test_ndcg_and_precision() -> None:
    assert m.ndcg([3, 2, 0, 0, 1]) == pytest.approx(
        (7 + 3 / math.log2(3) + 1 / math.log2(6)) / (7 + 3 / math.log2(3) + 1 / 2)
    )
    assert m.ndcg([3, 2, 1, 0]) == 1.0
    assert m.ndcg([0, 0, 0]) is None  # IDCG = 0 — компания пропускается
    assert m.precision_at([3, 2, 1, 0, 2]) == 0.6
    assert m.recall_rel3_at([0, 3, 0, 0, 0, 3]) == 0.5 and m.recall_rel3_at([1, 2]) is None


def test_spearman_kappa_direction() -> None:
    assert m.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert m.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert m.weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3]) == pytest.approx(1.0)
    assert m.weighted_kappa([0, 1, 2, 3], [1, 1, 2, 2]) == pytest.approx(2 / 3)  # посчитано вручную
    assert m.direction_score("risk", "risk") == 1.0 and m.direction_score("mixed", "risk") == 0.5
    assert m.direction_score("risk", "opportunity") == 0.0
    assert m.median([3, 1, 2]) == 2 and m.percentile([1, 2, 3, 4], 0.5) == 2


def test_gold_prefers_humans_and_counts_overlap() -> None:
    labels = [
        Label("C", "s1", 2, "risk", "llm"),
        Label("C", "s1", 3, "risk", "human:anna"),
        Label("C", "s1", 2, "risk", "human:oleg"),
        Label("C", "s1", 3, "risk", "human:final"),
        Label("C", "s2", 0, "none", "human:anna"),
        Label("C", "s3", 1, "risk", "llm"),
    ]
    g = gold_labels(labels)
    assert g.source == "human" and set(g.labels) == {("C", "s1"), ("C", "s2")}
    assert g.labels[("C", "s1")].labeler == "human:final" and g.overlap == 1
    llm_only = gold_labels([x for x in labels if x.labeler == "llm"])
    assert llm_only.source == "llm" and len(llm_only.labels) == 2 and llm_only.kappa is None


def test_offline_summary_from_report() -> None:
    from alfa_insight.services.quality import offline_summary

    rep = {
        "generated_at": "2026-10-24T00:00:00Z",
        "dataset": {"labels_source": "llm", "judgements": 60, "companies": 6, "kappa": None},
        "ranking": {
            "ndcg@5": 0.8,
            "p@5": 0.6,
            "baselines": {"industry_only": {"ndcg@5": 0.5}, "random": {"ndcg@5": 0.4}},
        },
        "generation": {"insights": 18, "grounded_share_llm": 0.98, "latency_ms": {"p50": 1}},
        "analyze": None,
    }
    s = offline_summary(rep)
    assert (
        s.ranking["ours"].ndcg5 == 0.8
        and s.ranking["industry_only"].ndcg5 == 0.5
        and s.analyze_p50_ms is None
    )
