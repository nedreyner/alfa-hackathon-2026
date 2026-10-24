from __future__ import annotations

import time

import pytest

from alfa_insight.ranking.chain import compute_exposure
from alfa_insight.ranking.scorer import impact_level, score_exposure
from alfa_insight.store.rankings import RankingStore

from .helpers import CFG, NOW, TAX, event, example_12, profile


def test_example_12_score() -> None:
    p, e = example_12()
    exp = compute_exposure(e, p, "cfo", CFG, TAX)
    comp = score_exposure(exp, e, p, "cfo", CFG, NOW)
    assert comp.relevance == pytest.approx(0.515, abs=1e-3)
    assert comp.importance_factor == pytest.approx(0.92, abs=1e-6)
    assert comp.freshness == pytest.approx(0.5 ** (6 / 48), abs=1e-6)
    assert comp.freshness_factor == pytest.approx(0.958, abs=1e-3)
    assert comp.trust_factor == pytest.approx(0.945, abs=1e-6)
    assert comp.region_bonus == 0
    assert comp.score == pytest.approx(0.429, abs=1e-3)
    assert impact_level(comp.score, e.importance, CFG) == "high"


def test_roles_reorder_fx_vs_supplier_prices() -> None:
    p = profile(
        "SYN-DEMO-04",
        "wholesale_chemicals",
        suppliers={"chemicals": 0.63},
        coverage=(0.9, 0.7),
        factors={"fx_cny": (0.5, 1, ["ВЭД: Китай (экспорт)"])},
    )
    fx = event(1, factors=[("fx_cny", 1, 1.0, 1.0)])
    prices = event(2, industries=[("chemicals", "prices_up", 1.0, 1.0)])

    def score(e, role):  # type: ignore[no-untyped-def]
        return score_exposure(compute_exposure(e, p, role, CFG, TAX), e, p, role, CFG, NOW).score

    assert score(fx, "treasurer") > score(prices, "treasurer")
    assert score(prices, "cfo") > score(fx, "cfo")


def test_region_bonus_exact_match() -> None:
    e_msk = event(industries=[("wholesale_metals", "prices_up", 1.0, 1.0)], geo=["RU", "RU-MOW"])
    in_region = profile("C", "wholesale_metals", region_code="RU-MOW")
    other = profile("C", "wholesale_metals", region_code="RU-SPE")
    no_code = profile("C", "wholesale_metals", region_code=None)
    for p, bonus in ((in_region, 0.10), (other, 0.0), (no_code, 0.0)):
        comp = score_exposure(compute_exposure(e_msk, p, "owner", CFG, TAX), e_msk, p, "owner", CFG, NOW)
        assert comp.region_bonus == bonus
    country_only = event(industries=[("wholesale_metals", "prices_up", 1.0, 1.0)], geo=["RU"])
    comp = score_exposure(
        compute_exposure(country_only, in_region, "owner", CFG, TAX),
        country_only,
        in_region,
        "owner",
        CFG,
        NOW,
    )
    assert comp.region_bonus == 0.0


def test_rank_all_on_seed(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    t = time.monotonic()
    n = seeded_ctx.ranking.rank_all()
    elapsed = time.monotonic() - t
    assert n > 0 and elapsed < 5.0, elapsed
    store = RankingStore(seeded_ctx.db)
    for company in seeded_ctx.demo.companies:
        strong = store.top(company.company_id, company.default_role, min_score=0.18, limit=50)
        assert len(strong) >= 3, (company.company_id, len(strong))
    assert seeded_ctx.ranking.rank_all() == n  # повторный расчёт стабилен
