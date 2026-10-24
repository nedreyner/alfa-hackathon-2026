from __future__ import annotations

import pytest

from alfa_insight.ranking.chain import build_graph, chain_preview, compute_exposure
from alfa_insight.ranking.effects import combine

from .helpers import CFG, TAX, event, example_12, profile


def test_example_12_paths() -> None:
    p, e = example_12()
    exp = compute_exposure(e, p, "cfo", CFG, TAX)
    by = {(x.channel, x.industry_id or x.factor_id): x for x in exp.paths}
    assert by[("supply", "metallurgy")].contribution == pytest.approx(
        0.9 * 1.2 * (0.9 * 0.34 / 0.9) * 1.0, abs=1e-6
    )
    assert by[("supply", "metallurgy")].contribution == pytest.approx(0.367, abs=1e-3)
    assert by[("own", "construction_buildings")].contribution == pytest.approx(0.221, abs=1e-3)
    assert by[("factor", "inflation")].contribution == pytest.approx(0.015, abs=1e-3)
    assert [x.id for x in exp.paths] == ["P1", "P2", "P3"] and exp.paths[0].channel == "supply"
    assert all(x.direction == "risk" for x in exp.paths) and exp.direction == "risk"
    assert exp.relevance == pytest.approx(0.515, abs=1e-3)
    assert exp.paths[0].basis == "blended" and exp.paths[0].raw_share == pytest.approx(0.34)
    assert exp.paths[0].feature_keys == ["suppliers.metallurgy"]


def test_key_rate_direction() -> None:
    p = profile("C", "wholesale_metals", factors={"key_rate": (1.0, -1, ["есть кредит"])})
    up = compute_exposure(event(factors=[("key_rate", 1, 1.0, 1.0)]), p, "cfo", CFG, TAX)
    down = compute_exposure(event(factors=[("key_rate", -1, 1.0, 1.0)]), p, "cfo", CFG, TAX)
    assert up.paths[0].direction == "risk" and up.direction == "risk"
    assert down.paths[0].direction == "opportunity" and down.direction == "opportunity"
    assert up.paths[0].mechanism == TAX.factor("key_rate").risk_text


def test_exporter_vs_importer_fx() -> None:
    exporter = profile(
        "SYN-DEMO-04", "wholesale_chemicals", factors={"fx_cny": (0.5, 1, ["ВЭД: Китай (экспорт)"])}
    )
    importer = profile("SYN-DEMO-03", "auto_trade", factors={"fx_cny": (0.7, -1, ["ВЭД: Китай (импорт)"])})
    e = event(factors=[("fx_cny", 1, 1.0, 1.0)])
    assert compute_exposure(e, exporter, "treasurer", CFG, TAX).direction == "opportunity"
    assert compute_exposure(e, importer, "treasurer", CFG, TAX).direction == "risk"


def test_coverage_basis() -> None:
    e = event(industries=[("building_materials", "prices_up", 1.0, 1.0)])
    prior = profile("C", "construction_buildings", coverage=(0.0, 0.0))
    path = compute_exposure(e, prior, "cfo", CFG, TAX).paths[0]
    typical = TAX.typical_suppliers("construction_buildings")["building_materials"]
    assert path.basis == "prior" and path.company_weight == pytest.approx(typical) and path.raw_share is None
    full = profile("C", "construction_buildings", suppliers={"building_materials": 0.5}, coverage=(1.0, 1.0))
    p2 = compute_exposure(e, full, "cfo", CFG, TAX).paths[0]
    assert p2.basis == "payments" and p2.company_weight == pytest.approx(0.5)


def test_mixed_rule() -> None:
    assert combine([(0.5, "risk"), (0.45, "opportunity")], 0.25) == "mixed"
    assert combine([(0.5, "risk"), (0.1, "opportunity")], 0.25) == "risk"
    assert combine([], 0.25) == "mixed"


def test_previews_per_channel() -> None:
    p, e = example_12()
    exp = compute_exposure(e, p, "cfo", CFG, TAX)
    assert chain_preview(e.title, exp, TAX) == (
        "Металлурги поднимают цены на арматуру на 8% с ноября → 34% ваших закупок — металлургия → "
        "риск: рост закупочных цен → себестоимость"
    )
    own = profile("C", "wholesale_metals")
    e_own = event(
        title="Цены на металлопрокат выросли", industries=[("wholesale_metals", "prices_up", 1.0, 1.0)]
    )
    assert chain_preview(e_own.title, compute_exposure(e_own, own, "owner", CFG, TAX), TAX) == (
        "Цены на металлопрокат выросли → ваша отрасль — опт: металлы и руды → возможность: рост цен реализации"
    )
    dem = profile("C", "metallurgy", buyers={"construction_buildings": 0.38}, coverage=(0.9, 0.9))
    e_dem = event(
        title="Застройщики сокращают запуск новых проектов из-за дорогой ипотеки и высокой ставки ЦБ",
        industries=[("construction_buildings", "demand_down", 1.0, 1.0)],
    )
    assert chain_preview(e_dem.title, compute_exposure(e_dem, dem, "owner", CFG, TAX), TAX) == (
        "Застройщики сокращают запуск новых проектов из-за дорогой… → 38% ваших продаж — строительство зданий, "
        "девелопмент → риск: покупатели сократят закупки, вырастет дебиторка"
    )
    fx = profile("C", "auto_trade", factors={"fx_cny": (0.7, -1, ["ВЭД: Китай (импорт)"])})
    e_fx = event(title="Юань подорожал", factors=[("fx_cny", 1, 1.0, 1.0)])
    assert chain_preview(e_fx.title, compute_exposure(e_fx, fx, "treasurer", CFG, TAX), TAX) == (
        "Юань подорожал → курс юаня: ВЭД: Китай (импорт) → риск: дорожает импорт из Китая и расчёты в юанях"
    )
    prior = profile("C", "construction_buildings")
    e_prior = event(title="Цемент дорожает", industries=[("building_materials", "prices_up", 1.0, 1.0)])
    assert chain_preview(e_prior.title, compute_exposure(e_prior, prior, "cfo", CFG, TAX), TAX) == (
        "Цемент дорожает → типично для отрасли ≈ 30% закупок — стройматериалы: цемент, бетон, стекло, кирпич → "
        "риск: рост закупочных цен → себестоимость"
    )


def test_graph_layout() -> None:
    p, e = example_12()
    g = build_graph(e.title, compute_exposure(e, p, "cfo", CFG, TAX), TAX, path_sources={"P1": ["E4"]})
    assert len(g.nodes) == 1 + 3 * 3 and len(g.edges) == 9
    exp_node = next(n for n in g.nodes if n.id == "P1-exposure")
    assert (exp_node.x, exp_node.y, exp_node.source_ids) == (560, 0, ["E4"])
    assert next(n for n in g.nodes if n.id == "P2-consequence").direction == "risk"
