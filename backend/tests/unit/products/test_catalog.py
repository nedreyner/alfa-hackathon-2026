from __future__ import annotations

from alfa_insight.data.models import CompanyProfile, ProductInfo, VedEntry
from alfa_insight.products.catalog import ProductCatalog, products_block
from alfa_insight.ranking.chain import compute_exposure
from tests.unit.ranking.helpers import CFG, ROOT, TAX, event, profile

CATALOG = ProductCatalog.load(ROOT / "config" / "products.yaml")


def _with(p: CompanyProfile, *, credit: bool = False, ved: str | None = None) -> CompanyProfile:
    upd: dict[str, object] = {}
    if credit:
        upd["products"] = {"credit": ProductInfo(has=True, amount_rub=1e9)}
    if ved:
        upd["ved"] = [VedEntry(country_iso2="CN", country_name="Китай", direction=ved, currencies=["CNY"])]  # type: ignore[arg-type]
    return p.model_copy(update=upd)


def _ids(p: CompanyProfile, ev, role="treasurer") -> list[str]:  # type: ignore[no-untyped-def]
    exp = compute_exposure(ev, p, role, CFG, TAX)
    return [c.product_id for c in CATALOG.match(exp, p, role)]


def test_catalog_valid_against_taxonomy() -> None:
    for prod in CATALOG.data.products:
        for t in prod.triggers:
            if t.factor:
                assert t.factor in TAX.factors, (prod.id, t.factor)
            if t.factor_prefix:
                assert any(f.startswith(t.factor_prefix) for f in TAX.factors)
            if t.effect:
                TAX.matrix_cell(t.channel, t.effect)  # бросит, если эффекта нет
        for iid in prod.conditions.industries:
            assert iid in TAX.industries
    assert CATALOG.disclaimer


def test_fx_risk_requires_ved() -> None:
    base = profile("A", "wholesale_metals", factors={"fx_cny": (0.9, -1, ["импорт из Китая"])})
    ev = event(factors=[("fx_cny", 1, 1.0, 1.0)])
    assert "fx_hedge_forward" in _ids(_with(base, ved="import"), ev)
    no_ved = _ids(base, ev)
    assert "fx_hedge_forward" not in no_ved and "ved_payments" not in no_ved


def test_key_rate_up_with_credit() -> None:
    base = profile("B", "construction_buildings", factors={"key_rate": (0.9, -1, ["кредит"])})
    up = event(factors=[("key_rate", 1, 1.0, 1.0)])
    ids = _ids(_with(base, credit=True), up)
    assert ids[:2] == ["interest_rate_hedge", "deposit_placement"]  # оба для казначея, порядок каталога
    assert "interest_rate_hedge" not in _ids(base, up)  # без кредита фиксация ставки не нужна
    down = event(factors=[("key_rate", -1, 1.0, 1.0)])
    assert "refinancing" in _ids(_with(base, credit=True), down)


def test_top3_and_order() -> None:
    p = _with(
        profile(
            "C", "wholesale_metals", suppliers={"metallurgy": 0.6}, coverage=(0.9, 0.0),
            factors={"customs_tariffs": (0.9, -1, ["импорт"]), "sanctions": (0.6, -1, ["ВЭД"])},
        ),
        ved="import", credit=True,
    )  # fmt: skip
    ev = event(
        industries=[("metallurgy", "prices_up", 1.0, 1.0), ("metallurgy", "supply_down", 1.0, 1.0)],
        factors=[("customs_tariffs", 1, 1.0, 1.0), ("sanctions", 1, 1.0, 1.0)],
    )
    exp = compute_exposure(ev, p, "cfo", CFG, TAX)
    cands = CATALOG.match(exp, p, "cfo")
    assert 1 <= len(cands) <= 3
    assert [c.score for c in cands] == sorted((c.score for c in cands), reverse=True)
    assert all(c.when for c in cands)
    block = products_block(cands)
    assert block.count("\n") == len(cands) - 1 and "Когда уместен" in block
    assert products_block([]) == "Кандидатов нет — не указывай product_id"
