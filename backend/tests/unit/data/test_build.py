from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from alfa_insight.data.build import build, detect_encoding
from alfa_insight.data.mapping import DataMapping
from alfa_insight.settings import Settings

COMPANIES_CP1251 = """ID;NAME;OKVED;REV;KLIENT;GRP;LOAN;LEASE;COUNTRY
C1;ООО «Металл»;46,72;20 000 000,5;Да;G1;1;0;КИТАЙ, ТУРЦИЯ
C2;АО «Строй»;41.20;1 000,0;Нет;G2;0;1;
C3;ООО «Сталь Урал»;24.10;16000000000;да;G1;0;0;Атлантида
"""


def _mapping(
    tmp: Path, payments_csv: str, mode: str, columns: dict[str, str | None], **extra: object
) -> DataMapping:
    (tmp / "companies.csv").write_bytes(COMPANIES_CP1251.encode("cp1251"))
    (tmp / "payments.csv").write_text(payments_csv, encoding="utf-8")
    raw = {
        "profile": "synthetic",
        "target_revenue_rub": 1_000_000,
        "tables": {
            "companies": {
                "path": str(tmp / "companies.csv"),
                "csv": {"delimiter": ";", "decimal": ","},
                "columns": {
                    "company_id": "ID",
                    "name": "NAME",
                    "okved": "OKVED",
                    "revenue_rub": "REV",
                    "is_client": "KLIENT",
                    "group_id": "GRP",
                },
                "transforms": {"is_client": {"true_values": ["да"]}},
            },
            "products": {"mode": "wide", "flags": {"credit": "LOAN", "leasing": "LEASE"}},
            "ved": {"mode": "wide", "country_column": "COUNTRY"},
            "payments": {
                "path": str(tmp / "payments.csv"),
                "csv": {"delimiter": ";"},
                "mode": mode,
                "columns": columns,
                **extra,
            },
        },
    }
    return DataMapping.model_validate(raw)


def _q(path: Path, sql: str) -> list[tuple[object, ...]]:
    conn = duckdb.connect(str(path), read_only=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_cp1251_decimal_comma_and_wide(tmp_path: Path, settings: Settings) -> None:
    payments = "PAYER;PAYEE;AMT;CNT\nC1;C2;100;1\nC2;C1;50;2\nX9;C1;10;1\nC1;C1;5;1\n"
    m = _mapping(
        tmp_path,
        payments,
        "payer_payee",
        {"payer_id": "PAYER", "payee_id": "PAYEE", "amount_rub": "AMT", "tx_count": "CNT"},
    )
    assert detect_encoding(tmp_path / "companies.csv", "auto") == "cp1251"
    res = build(settings, mapping=m, force=True)
    db = res.path
    rows = dict(_q(db, "SELECT company_id, revenue_rub FROM companies"))
    assert rows["C1"] == pytest.approx(20_000_000.5)
    assert rows["C2"] == pytest.approx(1000.0)
    assert _q(db, "SELECT name, okved, is_client FROM companies WHERE company_id = 'C1'") == [
        ("ООО «Металл»", "46.72", True)
    ]
    assert sorted(_q(db, "SELECT company_id, product_code FROM company_products")) == [
        ("C1", "credit"),
        ("C2", "leasing"),
    ]
    ved = sorted(_q(db, "SELECT company_id, country_raw, country_iso2 FROM company_ved"))
    assert ved == [("C1", "КИТАЙ", "CN"), ("C1", "ТУРЦИЯ", "TR"), ("C3", "Атлантида", None)]
    # payer_payee: строка → out для плательщика и in для получателя из companies; self исключён
    pay = sorted(_q(db, "SELECT company_id, counterparty_id, direction, amount_rub FROM payments"))
    assert pay == [
        ("C1", "C2", "in", 50.0),
        ("C1", "C2", "out", 100.0),
        ("C1", "X9", "in", 10.0),
        ("C2", "C1", "in", 100.0),
        ("C2", "C1", "out", 50.0),
        ("X9", "C1", "out", 10.0),
    ]
    assert res.meta["payments_self"] == 2
    assert res.meta["weight_basis"] == "amount"
    targets = {r[0] for r in _q(db, "SELECT company_id FROM target_companies")}
    assert targets == {"C1", "C3"}
    # повторная сборка без изменений пропускается
    assert build(settings, mapping=m).skipped


def test_company_counterparty_direction_and_weight_basis(tmp_path: Path, settings: Settings) -> None:
    payments = (
        "CO;CP;CPNAME;DIR;AMT;CNT\n"
        "C1;C3;;D;;3\n"  # внутри группы G1 — исключается
        "C1;Z1;ООО «МеталлТрейд»;D;;4\n"
        "C1;Z2;ООО «Вектор»;C;;\n"
        "C1;Z3;ИП Петров;C;;2\n"
    )
    m = _mapping(
        tmp_path,
        payments,
        "company_counterparty",
        {
            "company_id": "CO",
            "counterparty_id": "CP",
            "counterparty_name": "CPNAME",
            "direction": "DIR",
            "amount_rub": "AMT",
            "tx_count": "CNT",
        },
        direction_values={"out": ["D"], "in": ["C"]},
    )
    res = build(settings, mapping=m, force=True)
    assert res.meta["weight_basis"] == "links"  # amount пуст, tx_count заполнен в 75% < 80%
    pay = sorted(_q(res.path, "SELECT counterparty_id, direction FROM payments"))
    assert pay == [("Z1", "out"), ("Z2", "in"), ("Z3", "in")]
    ind = dict(_q(res.path, "SELECT counterparty_id, industry_id FROM counterparty_industry"))
    assert ind["Z1"] == "metallurgy" and ind["Z2"] == "unknown"


def test_weight_basis_tx_count(tmp_path: Path, settings: Settings) -> None:
    payments = "CO;CP;DIR;CNT\nC1;C2;D;3\nC1;Z1;C;4\nC1;Z2;C;1\n"
    m = _mapping(
        tmp_path,
        payments,
        "company_counterparty",
        {"company_id": "CO", "counterparty_id": "CP", "direction": "DIR", "tx_count": "CNT"},
        direction_values={"out": ["D"], "in": ["C"]},
    )
    assert build(settings, mapping=m, force=True).meta["weight_basis"] == "tx_count"
