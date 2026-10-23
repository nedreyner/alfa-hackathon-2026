"""SQL сборки DuckDB: нормализация CSV в логические таблицы (§4.2) и производные таблицы (§6)."""

from __future__ import annotations

from alfa_insight.data.mapping import Transform

DDL = """
CREATE TABLE companies (
  company_id VARCHAR PRIMARY KEY, inn VARCHAR, name VARCHAR NOT NULL,
  okved VARCHAR, okved_secondary VARCHAR[], region_code VARCHAR, region_name VARCHAR,
  revenue_rub DOUBLE, employees INTEGER, is_client BOOLEAN NOT NULL, group_id VARCHAR
);
CREATE TABLE company_products (
  company_id VARCHAR NOT NULL, product_code VARCHAR NOT NULL, amount_rub DOUBLE
);
CREATE TABLE company_ved (
  company_id VARCHAR NOT NULL, country_raw VARCHAR NOT NULL, country_iso2 VARCHAR,
  direction VARCHAR NOT NULL DEFAULT 'unknown', amount_rub DOUBLE
);
CREATE TABLE payments (
  company_id VARCHAR NOT NULL, counterparty_id VARCHAR NOT NULL, counterparty_inn VARCHAR,
  counterparty_name VARCHAR, counterparty_okved VARCHAR, direction VARCHAR NOT NULL,
  amount_rub DOUBLE, tx_count INTEGER, period VARCHAR
);
CREATE TABLE okved_industry (okved VARCHAR PRIMARY KEY, industry_id VARCHAR NOT NULL);
CREATE TABLE target_companies (company_id VARCHAR PRIMARY KEY);
CREATE TABLE build_meta (key VARCHAR PRIMARY KEY, value VARCHAR);
"""


def q(name: str) -> str:
    """Идентификатор в кавычках."""
    return '"' + name.replace('"', '""') + '"'


def lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def col(columns: dict[str, str | None], field: str) -> str:
    phys = columns.get(field)
    return f"NULLIF(trim({q(phys)}), '')" if phys else "NULL"


def num_expr(expr: str, decimal: str) -> str:
    cleaned = f"REPLACE(REPLACE({expr}, ' ', ''), chr(160), '')"
    if decimal == ",":
        cleaned = f"REPLACE({cleaned}, ',', '.')"
    return f"TRY_CAST({cleaned} AS DOUBLE)"


def okved_expr(expr: str) -> str:
    return f"NULLIF(rtrim(REPLACE(regexp_replace({expr}, '\\s', '', 'g'), ',', '.'), '.'), '')"


def apply_text(expr: str, tr: Transform | None, extra_map: dict[str, str] | None = None) -> str:
    if tr is None and not extra_map:
        return expr
    mapping = dict(extra_map or {})
    if tr is not None and tr.map:
        mapping.update(tr.map)
    if mapping:
        cases = " ".join(f"WHEN {lit(k)} THEN {lit(v)}" for k, v in mapping.items())
        expr = f"(CASE {expr} {cases} ELSE {expr} END)"
    if tr is not None and tr.strip_quotes:
        expr = f"trim(regexp_replace({expr}, '[«»\"“”„]', '', 'g'))"
    return expr


def bool_expr(expr: str, true_values: list[str]) -> str:
    values = ", ".join(lit(v.strip().lower()) for v in true_values)
    return f"COALESCE(lower(trim({expr})) IN ({values}), false)"


def weight_expr(basis: str) -> str:
    return {
        "amount": "COALESCE(p.amount_rub, 0)",
        "tx_count": "COALESCE(p.tx_count, 1)",
        "links": "1",
    }[basis]


# ── производные таблицы (§6) ──


def counterparty_industry_sql(counterparty_key: str) -> str:
    join = "c.company_id = cp.counterparty_id" if counterparty_key == "company_id" else "c.inn = cp.inn"
    return f"""
CREATE TABLE counterparty_industry AS
WITH cp AS (
  SELECT counterparty_id,
         any_value(counterparty_name)  AS name,
         any_value(counterparty_inn)   AS inn,
         any_value(counterparty_okved) AS okved_p
  FROM payments
  WHERE company_id IN (SELECT company_id FROM target_companies)
  GROUP BY counterparty_id
),
c AS (SELECT * FROM companies QUALIFY row_number() OVER (PARTITION BY {"company_id" if counterparty_key == "company_id" else "inn"}) = 1)
SELECT cp.counterparty_id, COALESCE(cp.name, c.name) AS name, cp.inn,
       COALESCE(o1.industry_id, o2.industry_id, ni.industry_id, 'unknown') AS industry_id,
       CASE WHEN o1.industry_id IS NOT NULL THEN 'companies_okved'
            WHEN o2.industry_id IS NOT NULL THEN 'payments_okved'
            WHEN ni.industry_id IS NOT NULL THEN 'name_keywords'
            ELSE 'unknown' END AS method,
       CASE WHEN o1.industry_id IS NOT NULL THEN 1.0
            WHEN o2.industry_id IS NOT NULL THEN 0.9
            WHEN ni.industry_id IS NOT NULL THEN 0.6
            ELSE 0.0 END AS confidence
FROM cp
LEFT JOIN c                 ON {join}
LEFT JOIN okved_industry o1 ON o1.okved = c.okved AND o1.industry_id <> 'unknown'
LEFT JOIN okved_industry o2 ON o2.okved = cp.okved_p AND o2.industry_id <> 'unknown'
LEFT JOIN name_industry ni  ON ni.counterparty_id = cp.counterparty_id
"""


def flows_sql(basis: str) -> str:
    w = weight_expr(basis)
    return f"""
CREATE TABLE flows_by_industry AS
WITH base AS (
  SELECT p.company_id, p.direction, ci.industry_id,
         SUM(COALESCE(p.amount_rub, 0))        AS amount_rub,
         SUM(COALESCE(p.tx_count, 1))          AS tx_count,
         COUNT(DISTINCT p.counterparty_id)     AS n_counterparties,
         SUM({w})                              AS weight
  FROM payments p
  JOIN counterparty_industry ci USING (counterparty_id)
  WHERE p.company_id IN (SELECT company_id FROM target_companies)
  GROUP BY 1, 2, 3
)
SELECT *,
       weight / NULLIF(SUM(weight) OVER (PARTITION BY company_id, direction), 0) AS share_total,
       CASE WHEN industry_id <> 'unknown' THEN
         weight / NULLIF(SUM(CASE WHEN industry_id <> 'unknown' THEN weight END)
                         OVER (PARTITION BY company_id, direction), 0)
       END AS share_known
FROM base;

CREATE TABLE coverage AS
SELECT company_id, direction, total_weight, known_weight,
       known_weight / NULLIF(total_weight, 0) AS coverage
FROM (
  SELECT company_id, direction,
         SUM(weight) AS total_weight,
         SUM(CASE WHEN industry_id <> 'unknown' THEN weight ELSE 0 END) AS known_weight
  FROM flows_by_industry GROUP BY 1, 2
);
"""


def top_counterparties_sql(basis: str, limit: int = 50) -> str:
    w = weight_expr(basis)
    return f"""
CREATE TABLE top_counterparties AS
SELECT * FROM (
  SELECT p.company_id, p.direction, p.counterparty_id,
         COALESCE(any_value(p.counterparty_name), any_value(ci.name)) AS name,
         any_value(p.counterparty_inn) AS inn, ci.industry_id,
         SUM({w}) AS weight,
         SUM({w}) / SUM(SUM({w})) OVER (PARTITION BY p.company_id, p.direction) AS share,
         row_number() OVER (PARTITION BY p.company_id, p.direction ORDER BY SUM({w}) DESC, p.counterparty_id) AS rank
  FROM payments p JOIN counterparty_industry ci USING (counterparty_id)
  WHERE p.company_id IN (SELECT company_id FROM target_companies)
  GROUP BY p.company_id, p.direction, p.counterparty_id, ci.industry_id
) WHERE rank <= {limit}
"""
