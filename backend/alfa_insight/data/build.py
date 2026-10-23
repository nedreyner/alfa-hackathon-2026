"""Сборка `analytics.duckdb` из CSV по маппингу (docs/03-data.md §4).

Сборка идёт во временный файл и атомарно заменяет основной (`os.replace`). Если хеш исходников,
маппинга и справочников не изменился, сборка пропускается (`force=True` пересобирает).
"""

from __future__ import annotations

import codecs
import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import duckdb

from alfa_insight.data import build_sql as S
from alfa_insight.data.mapping import CsvOptions, DataMapping, load_mapping
from alfa_insight.data.naming import match_name_industry
from alfa_insight.db.duck import connect_rw
from alfa_insight.log import get_logger
from alfa_insight.reference.taxonomy import Taxonomy, load_taxonomy
from alfa_insight.settings import Settings
from alfa_insight.timeutil import to_iso, utc_now

BUILD_VERSION = "3"
log = get_logger("data.build")

# Хук для T1.7: факторы и профили считаются в Python поверх собранных таблиц.
PostBuildHook = Callable[[duckdb.DuckDBPyConnection, "BuildContext"], None]
POST_BUILD_HOOKS: list[PostBuildHook] = []


@dataclass
class BuildContext:
    settings: Settings
    mapping: DataMapping
    taxonomy: Taxonomy
    weight_basis: str = "amount"
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuildResult:
    path: Path
    skipped: bool
    meta: dict[str, Any]


def resolve_data_path(settings: Settings, path: str) -> Path:
    """`data/...` — относительно DATA_DIR, остальное — относительно корня репозитория."""
    p = Path(path)
    if p.is_absolute():
        return p
    if p.parts and p.parts[0] == "data":
        return settings.data_path.joinpath(*p.parts[1:])
    return settings.repo_root / p


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sources_hash(settings: Settings, mapping: DataMapping, taxonomy: Taxonomy) -> tuple[str, dict[str, str]]:
    files = {str(p): _sha256(p) for p in _source_paths(settings, mapping)}
    payload = json.dumps(
        {
            "files": sorted(files.values()),
            "mapping": mapping.model_dump(mode="json"),
            "taxonomy": taxonomy.version,
            "build": BUILD_VERSION,
            "target": settings.target_revenue_rub,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest(), files


def _source_paths(settings: Settings, mapping: DataMapping) -> list[Path]:
    t = mapping.tables
    paths = [t.companies.path, t.payments.path]
    if t.products.mode == "long" and t.products.path:
        paths.append(t.products.path)
    if t.ved.mode == "long" and t.ved.path:
        paths.append(t.ved.path)
    resolved = [resolve_data_path(settings, p) for p in paths]
    for p in resolved:
        if not p.exists():
            raise FileNotFoundError(f"{p}: исходный CSV не найден (маппинг {mapping.profile})")
    return resolved


# ── подготовка CSV ──
def detect_encoding(path: Path, declared: str) -> str:
    if declared != "auto":
        return declared
    with path.open("rb") as fh:
        head = fh.read(3)
    if head == codecs.BOM_UTF8:
        return "utf-8-sig"
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                decoder.decode(chunk)
            decoder.decode(b"", final=True)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def prepare_csv(path: Path, opts: CsvOptions, tmp_dir: Path) -> Path:
    """DuckDB читает только UTF-8: остальное перекодируется потоком во временный файл."""
    encoding = detect_encoding(path, opts.encoding)
    if encoding == "utf-8":
        return path
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"{path.stem}.utf8.csv"
    with path.open(encoding=encoding, newline="") as src, out.open("w", encoding="utf-8", newline="") as dst:
        for chunk in iter(lambda: src.read(1 << 20), ""):
            dst.write(chunk)
    return out


def _stage(conn: duckdb.DuckDBPyConnection, name: str, path: Path, opts: CsvOptions) -> None:
    conn.execute(
        f"CREATE TABLE {name} AS SELECT * FROM read_csv({S.lit(str(path))}, delim={S.lit(opts.delimiter)}, "
        f"header={'true' if opts.header else 'false'}, all_varchar=true, quote='\"', escape='\"', "
        "ignore_errors=false, auto_detect=true)"
    )


# ── нормализация ──
def _load_companies(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> None:
    spec = ctx.mapping.tables.companies
    c, tr, dec = spec.columns, spec.transforms, spec.csv.decimal

    def text(f: str) -> str:
        return S.apply_text(S.col(c, f), tr.get(f))

    def number(f: str) -> str:
        expr = S.num_expr(S.col(c, f), dec)
        mult = tr.get(f).multiply if tr.get(f) else None  # type: ignore[union-attr]
        return f"({expr} * {mult})" if mult else expr

    is_client_tr = tr.get("is_client")
    true_values = (
        is_client_tr.true_values
        if is_client_tr and is_client_tr.true_values
        else ["1", "1.0", "true", "да", "y", "yes"]
    )
    name = text("name") if c.get("name") else "NULL"
    secondary = (
        f"list_filter(list_transform(string_split_regex({S.col(c, 'okved_secondary')}, '[,;]'), lambda x: {S.okved_expr('x')}), lambda x: x IS NOT NULL)"
        if c.get("okved_secondary")
        else "NULL"
    )
    conn.execute(f"""
        CREATE TEMP TABLE src_companies AS
        SELECT * FROM (
          SELECT {S.col(c, "company_id")} AS company_id,
                 {text("inn")} AS inn,
                 COALESCE({name}, 'Компания ' || {S.col(c, "company_id")}) AS name,
                 {S.okved_expr(S.col(c, "okved"))} AS okved,
                 {secondary} AS okved_secondary,
                 {text("region_code")} AS region_code,
                 {text("region_name")} AS region_name,
                 {number("revenue_rub")} AS revenue_rub,
                 TRY_CAST({S.num_expr(S.col(c, "employees"), dec)} AS INTEGER) AS employees,
                 {S.bool_expr(S.col(c, "is_client"), true_values)} AS is_client,
                 {text("group_id")} AS group_id
          FROM stg_companies
        ) WHERE company_id IS NOT NULL
    """)
    # Один id у разных компаний (разные ОКВЭД, выручка, группа) — неоднозначен и исключается целиком.
    # Полные дубли строк схлопываются.
    ambiguous = [
        r[0]
        for r in conn.execute("""
            SELECT company_id FROM src_companies GROUP BY company_id
            HAVING count(DISTINCT (COALESCE(okved, ''), COALESCE(revenue_rub, -1), COALESCE(group_id, ''), name)) > 1
        """).fetchall()
    ]
    conn.execute("""
        INSERT INTO companies
        SELECT company_id, any_value(inn), any_value(name), any_value(okved), any_value(okved_secondary),
               any_value(region_code), any_value(region_name), any_value(revenue_rub), any_value(employees),
               bool_or(is_client), any_value(group_id)
        FROM src_companies
        WHERE company_id NOT IN (SELECT company_id FROM src_companies GROUP BY company_id
            HAVING count(DISTINCT (COALESCE(okved, ''), COALESCE(revenue_rub, -1), COALESCE(group_id, ''), name)) > 1)
        GROUP BY company_id
    """)
    total = conn.execute("SELECT count(*) FROM src_companies").fetchone()[0]  # type: ignore[index]
    unique = conn.execute("SELECT count(DISTINCT company_id) FROM src_companies").fetchone()[0]  # type: ignore[index]
    ctx.meta["companies_rows"] = total
    ctx.meta["companies_duplicates"] = total - unique
    ctx.meta["companies_ambiguous_ids"] = ambiguous


def _load_products(conn: duckdb.DuckDBPyConnection, ctx: BuildContext, tmp: Path) -> None:
    spec = ctx.mapping.tables.products
    company_id = S.col(ctx.mapping.tables.companies.columns, "company_id")
    if spec.mode == "long":
        assert spec.path
        _stage(
            conn,
            "stg_products",
            prepare_csv(resolve_data_path(ctx.settings, spec.path), spec.csv, tmp),
            spec.csv,
        )
        c = spec.columns
        conn.execute(f"""
            INSERT INTO company_products
            SELECT {S.col(c, "company_id")}, lower({S.col(c, "product_code")}),
                   {S.num_expr(S.col(c, "amount_rub"), spec.csv.decimal)}
            FROM stg_products
            WHERE {S.col(c, "company_id")} IS NOT NULL AND {S.col(c, "product_code")} IS NOT NULL
        """)
        return
    dec = ctx.mapping.tables.companies.csv.decimal
    for code, flag in spec.flags.items():
        amount = (
            S.num_expr(f"NULLIF(trim({S.q(spec.amounts[code])}), '')", dec)
            if code in spec.amounts
            else "NULL"
        )
        conn.execute(f"""
            INSERT INTO company_products
            SELECT DISTINCT {company_id}, {S.lit(code)}, {amount}
            FROM stg_companies
            WHERE {S.bool_expr(f"NULLIF(trim({S.q(flag)}), '')", spec.true_values)} AND {company_id} IS NOT NULL
        """)


def _load_ved(conn: duckdb.DuckDBPyConnection, ctx: BuildContext, tmp: Path) -> None:
    spec = ctx.mapping.tables.ved
    if spec.mode == "none":
        return
    if spec.mode == "long":
        assert spec.path
        _stage(
            conn, "stg_ved", prepare_csv(resolve_data_path(ctx.settings, spec.path), spec.csv, tmp), spec.csv
        )
        c = spec.columns
        direction = S.col(c, "direction")
        conn.execute(f"""
            INSERT INTO company_ved
            SELECT {S.col(c, "company_id")}, {S.col(c, "country_raw")}, NULL,
                   CASE WHEN lower({direction}) IN ('import','export') THEN lower({direction}) ELSE 'unknown' END,
                   {S.num_expr(S.col(c, "amount_rub"), spec.csv.decimal)}
            FROM stg_ved WHERE {S.col(c, "country_raw")} IS NOT NULL
        """)
    else:
        assert spec.country_column
        company_id = S.col(ctx.mapping.tables.companies.columns, "company_id")
        pattern = "[" + "".join("\\" + s if s in "]\\^-" else s for s in spec.split) + "]"
        direction = (
            f"CASE WHEN lower(trim({S.q(spec.direction_column)})) IN ('import','export') "
            f"THEN lower(trim({S.q(spec.direction_column)})) ELSE 'unknown' END"
            if spec.direction_column
            else "'unknown'"
        )
        conn.execute(f"""
            INSERT INTO company_ved
            SELECT DISTINCT company_id, country_raw, NULL, direction, NULL FROM (
              SELECT {company_id} AS company_id, trim(unnest(string_split_regex({S.q(spec.country_column)}, {S.lit(pattern)}))) AS country_raw,
                     {direction} AS direction
              FROM stg_companies WHERE NULLIF(trim({S.q(spec.country_column)}), '') IS NOT NULL
            ) WHERE country_raw <> '' AND company_id IS NOT NULL
        """)
    conn.execute("DELETE FROM company_ved WHERE company_id NOT IN (SELECT company_id FROM companies)")
    raws = [r[0] for r in conn.execute("SELECT DISTINCT country_raw FROM company_ved").fetchall()]
    rows = []
    for raw in raws:
        country = ctx.taxonomy.country_by_name(raw)
        rows.append((raw, country.iso2 if country else None))
    if rows:
        conn.execute("CREATE TEMP TABLE ved_iso (raw VARCHAR, iso2 VARCHAR)")
        conn.executemany("INSERT INTO ved_iso VALUES (?, ?)", rows)
        conn.execute(
            "UPDATE company_ved SET country_iso2 = ved_iso.iso2 FROM ved_iso WHERE company_ved.country_raw = ved_iso.raw"
        )
    ctx.meta["ved_unrecognized"] = sorted(raw for raw, iso in rows if iso is None)


def _load_payments(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> None:
    spec = ctx.mapping.tables.payments
    c, dec = spec.columns, spec.csv.decimal
    amount = S.num_expr(S.col(c, "amount_rub"), dec)
    tx = f"TRY_CAST({S.num_expr(S.col(c, 'tx_count'), dec)} AS INTEGER)"
    if spec.mode == "company_counterparty":
        raw_dir = S.col(c, "direction")
        if spec.direction_values is None or not c.get("direction"):
            direction = "'out'"
            ctx.meta["direction_unknown"] = True
        else:
            out_vals = ", ".join(S.lit(v.lower()) for v in spec.direction_values.get("out", []))
            in_vals = ", ".join(S.lit(v.lower()) for v in spec.direction_values.get("in", []))
            direction = (
                f"CASE WHEN lower({raw_dir}) IN ({out_vals or 'NULL'}) THEN 'out' "
                f"WHEN lower({raw_dir}) IN ({in_vals or 'NULL'}) THEN 'in' END"
            )
        select = f"""
            SELECT {S.col(c, "company_id")} AS company_id, {S.col(c, "counterparty_id")} AS counterparty_id,
                   {S.col(c, "counterparty_inn")} AS counterparty_inn, {S.col(c, "counterparty_name")} AS counterparty_name,
                   {S.okved_expr(S.col(c, "counterparty_okved"))} AS counterparty_okved, {direction} AS direction,
                   {amount} AS amount_rub, {tx} AS tx_count, {S.col(c, "period")} AS period
            FROM stg_payments
        """
    else:
        payer, payee = S.col(c, "payer_id"), S.col(c, "payee_id")
        common = f"{amount} AS amount_rub, {tx} AS tx_count, {S.col(c, 'period')} AS period"
        select = f"""
            SELECT {payer} AS company_id, {payee} AS counterparty_id, NULL AS counterparty_inn,
                   NULL AS counterparty_name, NULL AS counterparty_okved, 'out' AS direction, {common}
            FROM stg_payments
            UNION ALL
            SELECT {payee}, {payer}, NULL, NULL, NULL, 'in', {common}
            FROM stg_payments WHERE {payee} IN (SELECT company_id FROM companies)
        """
    conn.execute(f"CREATE TEMP TABLE pay_all AS {select}")
    stats = conn.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE company_id = counterparty_id),
               count(*) FILTER (WHERE direction IS NULL),
               count(*) FILTER (WHERE amount_rub IS NULL OR amount_rub <= 0),
               count(*) FILTER (WHERE amount_rub IS NOT NULL),
               count(*) FILTER (WHERE tx_count IS NOT NULL)
        FROM pay_all
    """).fetchone()
    assert stats is not None
    total, self_pay, no_dir, bad_amount, has_amount, has_tx = stats
    key_col = "company_id" if spec.counterparty_key == "company_id" else "inn"
    intragroup_filter = (
        f"""AND NOT EXISTS (
              SELECT 1 FROM companies a JOIN companies b ON a.group_id = b.group_id
              WHERE a.company_id = p.company_id AND b.{key_col} = p.{"counterparty_id" if key_col == "company_id" else "counterparty_inn"}
                AND a.group_id IS NOT NULL)"""
        if spec.exclude_intragroup
        else ""
    )
    self_filter = "AND p.company_id <> p.counterparty_id" if spec.exclude_self else ""
    conn.execute(f"""
        INSERT INTO payments
        SELECT * FROM pay_all p
        WHERE p.company_id IS NOT NULL AND p.counterparty_id IS NOT NULL AND p.direction IS NOT NULL
          {self_filter} {intragroup_filter}
    """)
    kept = conn.execute("SELECT count(*) FROM payments").fetchone()[0]  # type: ignore[index]
    ctx.meta.update(
        payments_source_rows=conn.execute("SELECT count(*) FROM stg_payments").fetchone()[0],  # type: ignore[index]
        payments_rows=total,
        payments_self=self_pay,
        payments_no_direction=no_dir,
        payments_bad_amount=bad_amount,
        payments_intragroup=total - kept - (self_pay if spec.exclude_self else 0) - no_dir,
        payments_kept=kept,
    )
    basis = ctx.mapping.weight_basis
    if basis == "auto":
        basis = (
            "amount"
            if total and has_amount / total >= 0.8
            else "tx_count"
            if total and has_tx / total >= 0.8
            else "links"
        )
    ctx.weight_basis = basis
    ctx.meta["weight_basis"] = basis


def _okved_industry(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> None:
    codes = conn.execute("""
        SELECT okved FROM companies WHERE okved IS NOT NULL
        UNION SELECT counterparty_okved FROM payments WHERE counterparty_okved IS NOT NULL
    """).fetchall()
    rows = [(code, ctx.taxonomy.match_okved(code)) for (code,) in codes]
    if rows:
        conn.executemany("INSERT INTO okved_industry VALUES (?, ?)", rows)


def _name_industry(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> None:
    conn.execute(
        "CREATE TABLE name_industry (counterparty_id VARCHAR PRIMARY KEY, industry_id VARCHAR NOT NULL)"
    )
    names = conn.execute("""
        SELECT counterparty_id, any_value(counterparty_name) FROM payments
        WHERE company_id IN (SELECT company_id FROM target_companies) AND counterparty_name IS NOT NULL
        GROUP BY counterparty_id
    """).fetchall()
    rows = []
    for cid, name in names:
        industry = match_name_industry(name, ctx.taxonomy)
        if industry:
            rows.append((cid, industry))
    if rows:
        conn.executemany("INSERT INTO name_industry VALUES (?, ?)", rows)


def _derived(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> None:
    conn.execute(S.counterparty_industry_sql(ctx.mapping.tables.payments.counterparty_key))
    conn.execute(S.flows_sql(ctx.weight_basis))
    conn.execute(S.top_counterparties_sql(ctx.weight_basis))


def read_meta(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        conn = duckdb.connect(str(path), read_only=True)
    except duckdb.Error:
        return None
    try:
        rows = conn.execute("SELECT key, value FROM build_meta").fetchall()
    except duckdb.Error:
        return None
    finally:
        conn.close()
    return {k: json.loads(v) for k, v in rows}


def build(settings: Settings, *, force: bool = False, mapping: DataMapping | None = None) -> BuildResult:
    from alfa_insight.data.validate import run_checks, store_checks

    mapping = mapping or load_mapping(settings.config_path, settings.data_profile)
    taxonomy = load_taxonomy(settings.reference_dir)
    digest, files = sources_hash(settings, mapping, taxonomy)
    target = settings.duckdb_path
    existing = read_meta(target)
    if not force and existing and existing.get("sources_hash") == digest:
        log.info("data_build_skipped", path=str(target))
        return BuildResult(target, True, existing)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp_dir = settings.runtime_dir / "tmp"
    for p in (tmp, tmp.with_name(tmp.name + ".wal")):
        p.unlink(missing_ok=True)
    ctx = BuildContext(settings=settings, mapping=mapping, taxonomy=taxonomy)
    conn = connect_rw(tmp)
    try:
        conn.execute(S.DDL)
        comp = mapping.tables.companies
        _stage(
            conn,
            "stg_companies",
            prepare_csv(resolve_data_path(settings, comp.path), comp.csv, tmp_dir),
            comp.csv,
        )
        _load_companies(conn, ctx)
        _load_products(conn, ctx, tmp_dir)
        conn.execute(
            "DELETE FROM company_products WHERE company_id NOT IN (SELECT company_id FROM companies)"
        )
        _load_ved(conn, ctx, tmp_dir)
        pay = mapping.tables.payments
        _stage(
            conn,
            "stg_payments",
            prepare_csv(resolve_data_path(settings, pay.path), pay.csv, tmp_dir),
            pay.csv,
        )
        _load_payments(conn, ctx)
        _okved_industry(conn, ctx)
        conn.execute(
            "INSERT INTO target_companies SELECT company_id FROM companies WHERE revenue_rub >= ?",
            [mapping.target_revenue_rub],
        )
        _name_industry(conn, ctx)
        _derived(conn, ctx)
        for hook in POST_BUILD_HOOKS:
            hook(conn, ctx)
        for stg in ("stg_companies", "stg_payments", "stg_products", "stg_ved"):
            conn.execute(f"DROP TABLE IF EXISTS {stg}")
        ctx.meta.update(
            sources_hash=digest,
            sources=files,
            data_profile=mapping.profile,
            built_at=to_iso(utc_now()),
            taxonomy_version=taxonomy.version,
            build_version=BUILD_VERSION,
            target_revenue_rub=mapping.target_revenue_rub,
        )
        conn.executemany(
            "INSERT INTO build_meta VALUES (?, ?)",
            [(k, json.dumps(v, ensure_ascii=False)) for k, v in ctx.meta.items()],
        )
        store_checks(conn, run_checks(conn, ctx.meta))
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    os.replace(tmp, target)
    log.info("data_build_done", path=str(target), weight_basis=ctx.weight_basis)
    return BuildResult(target, False, ctx.meta)
