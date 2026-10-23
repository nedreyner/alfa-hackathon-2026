"""Golden-тест профилей на мини-фикстуре: каскад, доли, покрытие, факторы и причины."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from alfa_insight.data.build import build
from alfa_insight.data.mapping import DataMapping
from alfa_insight.data.models import CompanyProfile
from alfa_insight.settings import Settings

COMPANIES = """company_id,inn,name,okved,revenue_rub,is_client,group_id
T1,0012345678,ООО «Тест Металл»,46.72.2,2000000000,true,G1
T2,0012345679,АО «Тест Строй»,41.20,3000000000,true,G2
S1,0012345680,АО «Сталь»,24.10,100000000,false,G3
S2,0012345681,ООО «Транс»,49.41,100000000,false,G1
B1,0012345682,ООО «Подряд»,41.20,100000000,false,G4
"""
PRODUCTS = "company_id,product_code,amount_rub\nT1,credit,100\nT1,leasing,\n"
VED = "company_id,country_raw,direction,amount_rub\nT1,КИТАЙ,import,\n"
PAYMENTS = """company_id,counterparty_id,counterparty_inn,counterparty_name,counterparty_okved,direction,amount_rub,tx_count
T1,S1,,,,out,600,1
T1,X1,0099999991,ООО «МеталлПрокат»,,out,200,1
T1,X2,0099999992,ООО «Ромашка»,49.41,out,100,1
T1,X3,0099999993,ООО «Вектор»,,out,100,1
T1,S2,,,,out,500,1
T1,T1,,,,out,50,1
T1,T2,,,,in,700,1
T1,B1,,,,in,300,1
T1,X4,001234567890,ИП Сидоров А. А.,,in,100,1
T2,T1,,,,out,700,1
T2,B1,,,,in,300,1
"""


@pytest.fixture
def db(tmp_path: Path, settings: Settings) -> Path:
    for name, text in {"c.csv": COMPANIES, "p.csv": PRODUCTS, "v.csv": VED, "pay.csv": PAYMENTS}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    ident = lambda *cols: {c: c for c in cols}  # noqa: E731
    mapping = DataMapping.model_validate(
        {
            "profile": "synthetic",
            "target_revenue_rub": 1_000_000_000,
            "tables": {
                "companies": {
                    "path": str(tmp_path / "c.csv"),
                    "columns": ident(
                        "company_id", "inn", "name", "okved", "revenue_rub", "is_client", "group_id"
                    ),
                    "transforms": {"is_client": {"true_values": ["true"]}},
                },
                "products": {
                    "mode": "long",
                    "path": str(tmp_path / "p.csv"),
                    "columns": ident(*["company_id", "product_code", "amount_rub"]),
                },
                "ved": {
                    "mode": "long",
                    "path": str(tmp_path / "v.csv"),
                    "columns": ident(*["company_id", "country_raw", "direction", "amount_rub"]),
                },
                "payments": {
                    "path": str(tmp_path / "pay.csv"),
                    "columns": ident(
                        "company_id",
                        "counterparty_id",
                        "counterparty_inn",
                        "counterparty_name",
                        "counterparty_okved",
                        "direction",
                        "amount_rub",
                        "tx_count",
                    ),
                    "direction_values": {"out": ["out"], "in": ["in"]},
                },
            },
        }
    )
    return build(settings, mapping=mapping, force=True).path


def _profile(db: Path, cid: str) -> CompanyProfile:
    conn = duckdb.connect(str(db), read_only=True)
    try:
        row = conn.execute("SELECT profile_json FROM profiles WHERE company_id = ?", [cid]).fetchone()
    finally:
        conn.close()
    assert row is not None
    return CompanyProfile.model_validate_json(row[0])


def test_cascade_methods_and_masking(db: Path) -> None:
    conn = duckdb.connect(str(db), read_only=True)
    rows = {
        r[0]: r[1:]
        for r in conn.execute(
            "SELECT counterparty_id, industry_id, method, confidence, name FROM counterparty_industry"
        ).fetchall()
    }
    top = conn.execute("SELECT name FROM top_counterparties WHERE counterparty_id = 'X4'").fetchone()
    conn.close()
    assert rows["S1"][:3] == ("metallurgy", "companies_okved", 1.0)
    assert rows["X2"][:3] == ("transport_logistics", "payments_okved", 0.9)
    assert rows["X1"][:3] == ("metallurgy", "name_keywords", 0.6)
    assert rows["X3"][:3] == ("unknown", "unknown", 0.0)
    assert rows["X4"][3] == "ИП (контрагент)" and top == ("ИП (контрагент)",)
    assert "S2" not in rows  # платёж внутри группы исключён


def test_shares_and_coverage(db: Path) -> None:
    p = _profile(db, "T1")
    sup = {s.industry_id: s for s in p.suppliers_mix}
    assert set(sup) == {"metallurgy", "transport_logistics"}
    assert sup["metallurgy"].share_total == pytest.approx(0.8)
    assert sup["metallurgy"].share == pytest.approx(800 / 900, abs=1e-6)
    assert sup["metallurgy"].n_counterparties == 2
    assert sup["transport_logistics"].share_total == pytest.approx(0.1)
    assert p.coverage["supply"] == pytest.approx(0.9)
    buy = {s.industry_id: s for s in p.buyers_mix}
    assert buy["construction_buildings"].share_total == pytest.approx(1000 / 1100, abs=1e-6)
    assert p.coverage["demand"] == pytest.approx(1000 / 1100, abs=1e-6)
    assert p.top_buyer_share == pytest.approx(700 / 1100, abs=1e-6)
    assert p.industry_id == "wholesale_metals" and p.revenue_bucket == "15-30"


def test_factor_exposure_and_reasons(db: Path) -> None:
    p = _profile(db, "T1")
    f = {x.factor_id: x for x in p.factor_exposure}
    expected = {
        "key_rate": (1.0, -1),
        "credit_conditions": (0.4, -1),
        "customs_tariffs": (1.0, -1),
        "fx_cny": (1.0, -1),
        "fx_usd": (0.7, -1),
        "gov_spending": (0.3, 1),
        "mortgage_market": (0.3, 1),
        "sanctions": (0.6, -1),
        "cross_border_payments": (0.6, -1),
        "logistics": (0.4, -1),
        "tax_burden": (0.3, -1),
        "labor_costs": (0.2, -1),
        "inflation": (0.2, -1),
        "payment_discipline": (0.5, -1),
    }
    assert {k: (v.exposure, v.sign) for k, v in f.items()} == pytest.approx(expected)
    assert f["key_rate"].reasons == [
        "отрасль: Опт: металлы и руды",
        "общий фактор",
        "есть кредит",
        "есть лизинг",
    ]
    assert f["fx_cny"].reasons == ["отрасль: Опт: металлы и руды", "ВЭД: Китай (импорт)"]
    assert f["payment_discipline"].reasons == ["общий фактор", "концентрация покупателей: 64% у одного"]


def test_features_keys(db: Path) -> None:
    p = _profile(db, "T1")
    feats = {x.key: x for x in p.features}
    assert feats["suppliers.metallurgy"].value == "80% (данные по 90% платежей)"
    assert feats["ved.country.CN"].value == "Китай (импорт)"
    assert {
        "industry.main",
        "revenue",
        "products.credit",
        "products.leasing",
        "coverage.supply",
        "factor.key_rate",
        "group",
    } <= set(feats)
    # у T2 нет данных о поставщиках вне фикстуры → признаки по своим платежам
    t2 = _profile(db, "T2")
    assert {x.key for x in t2.features} >= {"suppliers.wholesale_metals", "buyers.construction_buildings"}
    assert len(json.dumps(p.model_dump(mode="json"))) < 20_000


def test_synthetic_profiles(synthetic_duckdb: Path) -> None:
    conn = duckdb.connect(str(synthetic_duckdb), read_only=True)
    n_targets = conn.execute("SELECT count(*) FROM target_companies").fetchone()
    n_profiles = conn.execute("SELECT count(*) FROM profiles").fetchone()
    row = conn.execute("SELECT profile_json FROM profiles WHERE company_id = 'SYN-DEMO-02'").fetchone()
    conn.close()
    assert n_targets == n_profiles
    assert row is not None
    p = CompanyProfile.model_validate_json(row[0])
    metallurgy = next(s for s in p.suppliers_mix if s.industry_id == "metallurgy")
    assert metallurgy.share_total == pytest.approx(0.34, abs=0.01)
    assert p.coverage["supply"] == pytest.approx(0.90, abs=0.02)
