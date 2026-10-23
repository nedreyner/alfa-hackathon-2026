"""Проверка данных после сборки (docs/03-data.md §10): stdout, data_quality.json и таблица data_quality."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Literal

import duckdb

Status = Literal["ok", "warn", "error"]


@dataclass
class Check:
    check: str
    value: Any
    status: Status = "ok"
    details: dict[str, Any] = field(default_factory=dict)


def _one(conn: duckdb.DuckDBPyConnection, sql: str) -> Any:
    row = conn.execute(sql).fetchone()
    return None if row is None else row[0]


def _has(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    return bool(_one(conn, f"SELECT count(*) FROM information_schema.tables WHERE table_name = '{table}'"))


def run_checks(conn: duckdb.DuckDBPyConnection, meta: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    real = meta.get("data_profile") == "real"

    for table in ("companies", "company_products", "company_ved", "payments"):
        n = _one(conn, f"SELECT count(*) FROM {table}")
        status: Status = "error" if n == 0 and table in ("companies", "payments") else "ok"
        if n == 0 and table not in ("companies", "payments"):
            status = "warn"
        checks.append(Check(f"rows.{table}", n, status))

    n_targets = _one(conn, "SELECT count(*) FROM target_companies")
    status = "error" if n_targets == 0 else ("warn" if real and not 80 <= n_targets <= 150 else "ok")
    checks.append(Check("targets.count", n_targets, status))
    if not n_targets:
        return checks

    clients = _one(
        conn,
        "SELECT avg(is_client::INT) FROM companies WHERE company_id IN (SELECT company_id FROM target_companies)",
    )
    n_clients = _one(
        conn,
        "SELECT count(*) FILTER (WHERE is_client) FROM companies WHERE company_id IN (SELECT company_id FROM target_companies)",
    )
    checks.append(
        Check(
            "targets.client_share",
            round(clients, 3),
            "warn" if clients < 0.8 else "ok",
            {"clients": n_clients},
        )
    )

    industries = conn.execute("""
        SELECT COALESCE(o.industry_id, 'unknown') AS industry_id, count(*) AS n
        FROM companies c JOIN target_companies t USING (company_id)
        LEFT JOIN okved_industry o ON o.okved = c.okved
        GROUP BY 1 ORDER BY n DESC, industry_id
    """).fetchall()
    unknown_share = sum(n for i, n in industries if i == "unknown") / n_targets
    checks.append(
        Check(
            "targets.industries",
            round(unknown_share, 3),
            "error" if unknown_share > 0.4 else "warn" if unknown_share > 0.1 else "ok",
            {"top10": dict(industries[:10]), "unknown_share": round(unknown_share, 3)},
        )
    )

    for code in ("credit", "leasing"):
        share = _one(
            conn,
            f"""SELECT count(DISTINCT company_id)::DOUBLE / {n_targets} FROM company_products
                WHERE product_code = '{code}' AND company_id IN (SELECT company_id FROM target_companies)""",
        )
        checks.append(Check(f"targets.product_share.{code}", round(share, 3)))

    ved_share = _one(
        conn,
        f"SELECT count(DISTINCT company_id)::DOUBLE / {n_targets} FROM company_ved WHERE company_id IN (SELECT company_id FROM target_companies)",
    )
    total_ved = _one(conn, "SELECT count(*) FROM company_ved") or 0
    unrec = _one(conn, "SELECT count(*) FROM company_ved WHERE country_iso2 IS NULL") or 0
    top = conn.execute(
        "SELECT COALESCE(country_iso2, '?'), count(*) n FROM company_ved GROUP BY 1 ORDER BY n DESC LIMIT 8"
    ).fetchall()
    unrec_share = unrec / total_ved if total_ved else 0.0
    checks.append(
        Check(
            "ved.fill_and_countries",
            round(ved_share, 3),
            "warn" if unrec_share > 0.05 else "ok",
            {
                "top_countries": dict(top),
                "unrecognized_share": round(unrec_share, 3),
                "unrecognized": meta.get("ved_unrecognized", [])[:20],
            },
        )
    )

    with_pay = _one(
        conn,
        "SELECT count(DISTINCT company_id) FROM payments WHERE company_id IN (SELECT company_id FROM target_companies)",
    )
    pay_share = with_pay / n_targets
    checks.append(
        Check(
            "targets.with_payments",
            round(pay_share, 3),
            "error" if pay_share < 0.5 else "warn" if pay_share < 0.9 else "ok",
            {"companies": with_pay},
        )
    )

    if _has(conn, "coverage"):
        cov = [
            r[0] for r in conn.execute("SELECT coverage FROM coverage WHERE coverage IS NOT NULL").fetchall()
        ]
        med = median(cov) if cov else 0.0
        # В реальных данных контрагенты вне таблицы компаний не имеют ни ОКВЭД, ни названия:
        # низкое покрытие — свойство набора, ранжирование смешивает доли с типовыми (07-ranking §5).
        error_below = 0.15 if real else 0.3
        checks.append(
            Check(
                "counterparty_coverage.median",
                round(med, 3),
                "error" if med < error_below else "warn" if med < 0.6 else "ok",
            )
        )
        methods = dict(
            conn.execute("SELECT method, count(*) FROM counterparty_industry GROUP BY 1").fetchall()
        )
        checks[-1].details["methods"] = methods

    directions = dict(conn.execute("SELECT direction, count(*) FROM payments GROUP BY 1").fetchall())
    total_pay = sum(directions.values()) or 1
    min_side = min(directions.get("in", 0), directions.get("out", 0)) / total_pay
    status = (
        "error"
        if not directions.get("in") or not directions.get("out")
        else "warn"
        if min_side < 0.1
        else "ok"
    )
    if meta.get("direction_unknown"):
        status = "warn"
    checks.append(Check("payments.direction_balance", round(min_side, 3), status, directions))

    rows = meta.get("payments_rows") or 1
    bad = (meta.get("payments_bad_amount") or 0) / rows
    checks.append(Check("payments.bad_amount_share", round(bad, 4), "warn" if bad > 0.05 else "ok"))
    self_pay = meta.get("payments_self") or 0
    checks.append(
        Check(
            "payments.self",
            self_pay,
            "warn" if self_pay > 0 else "ok",
            {"intragroup": meta.get("payments_intragroup")},
        )
    )
    basis = meta.get("weight_basis", "amount")
    checks.append(Check("payments.weight_basis", basis, "warn" if basis != "amount" else "ok"))
    checks.append(
        Check(
            "payments.source_rows",
            meta.get("payments_source_rows"),
            details={"after_cleaning": meta.get("payments_kept")},
        )
    )
    dups = meta.get("companies_duplicates", 0)
    ambiguous = meta.get("companies_ambiguous_ids", [])
    remaining = _one(conn, "SELECT count(*) - count(DISTINCT company_id) FROM companies")
    checks.append(
        Check(
            "companies.duplicate_ids",
            dups,
            "error" if remaining else "warn" if dups else "ok",
            {"ambiguous_excluded": ambiguous[:20]} if ambiguous else {},
        )
    )
    return checks


def store_checks(conn: duckdb.DuckDBPyConnection, checks: list[Check]) -> None:
    conn.execute("DROP TABLE IF EXISTS data_quality")
    conn.execute(
        'CREATE TABLE data_quality ("check" VARCHAR, value VARCHAR, status VARCHAR, details VARCHAR)'
    )
    conn.executemany(
        "INSERT INTO data_quality VALUES (?, ?, ?, ?)",
        [
            (
                c.check,
                json.dumps(c.value, ensure_ascii=False),
                c.status,
                json.dumps(c.details, ensure_ascii=False),
            )
            for c in checks
        ],
    )


def write_report(checks: list[Check], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(c) for c in checks], ensure_ascii=False, indent=2), encoding="utf-8")


def format_table(checks: list[Check]) -> str:
    width = max(len(c.check) for c in checks)
    lines = [f"{'проверка'.ljust(width)}  статус  значение"]
    for c in checks:
        detail = json.dumps(c.details, ensure_ascii=False) if c.details else ""
        lines.append(f"{c.check.ljust(width)}  {c.status.ljust(6)}  {c.value}  {detail}".rstrip())
    return "\n".join(lines)


def validate_file(duckdb_path: Path, report_path: Path) -> list[Check]:
    from alfa_insight.data.build import read_meta

    meta = read_meta(duckdb_path)
    if meta is None:
        raise FileNotFoundError(f"{duckdb_path}: нет собранной базы, выполните `alfa data build`")
    conn = duckdb.connect(str(duckdb_path))
    try:
        checks = run_checks(conn, meta)
        store_checks(conn, checks)
    finally:
        conn.close()
    write_report(checks, report_path)
    return checks
