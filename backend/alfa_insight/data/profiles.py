"""Профили целевых компаний: сборка при `alfa data build` (§6.5, §7) и чтение с правками (`ProfileStore`)."""

from __future__ import annotations

import hashlib
import json
import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import duckdb

from alfa_insight.data.factors import compute_factors, exposure_level
from alfa_insight.data.models import (
    CompanyProfile,
    CompanySummary,
    Feature,
    IndustryShare,
    ProductInfo,
    RevenueBucket,
    VedEntry,
)
from alfa_insight.db.duck import DuckReader
from alfa_insight.errors import NotFoundError
from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy
from alfa_insight.store.profiles import Override, ProfileOverridesRepo

if TYPE_CHECKING:
    from alfa_insight.data.build import BuildContext

MIX_TOP = 10
PRODUCT_NAMES = {
    "credit": "кредит",
    "leasing": "лизинг",
    "deposit": "депозит",
    "guarantee": "банковская гарантия",
    "factoring": "факторинг",
    "acquiring": "эквайринг",
    "salary": "зарплатный проект",
    "fx": "валютные операции",
    "other": "прочие продукты",
}
DIRECTION_RU = {"import": "импорт", "export": "экспорт", "unknown": "направление не указано"}
BUCKET_RU = {
    "15-30": "15–30 млрд ₽",
    "30-100": "30–100 млрд ₽",
    "100-500": "100–500 млрд ₽",
    "500+": "больше 500 млрд ₽",
    "unknown": "нет данных",
}
IP_LABEL = "ИП (контрагент)"


def revenue_bucket(revenue: float | None) -> RevenueBucket:
    if revenue is None:
        return "unknown"
    bn = revenue / 1e9
    if bn < 30:
        return "15-30"
    if bn < 100:
        return "30-100"
    if bn < 500:
        return "100-500"
    return "500+"


def pct(x: float) -> str:
    return f"{round(x * 100)}%"


def country_display(taxonomy: Taxonomy, iso2: str | None, raw: str) -> str:
    if iso2 and iso2 in taxonomy.countries:
        name = taxonomy.countries[iso2].names[0]
        return name.upper() if len(name) <= 3 else name[:1].upper() + name[1:]
    return raw.strip().capitalize()


def is_individual(inn: str | None, name: str | None) -> bool:
    digits = (inn or "").strip()
    return (len(digits) == 12 and digits.isdigit()) or (name or "").strip().upper().startswith("ИП ")


def mask_individuals(conn: duckdb.DuckDBPyConnection) -> None:
    """ИП среди контрагентов — персональные данные: название заменяется на «ИП (контрагент)»."""
    for table in ("counterparty_industry", "top_counterparties"):
        conn.execute(
            f"""UPDATE {table} SET name = ?
                WHERE (length(trim(inn)) = 12 AND regexp_full_match(trim(inn), '[0-9]+'))
                   OR upper(trim(name)) LIKE 'ИП %'""",
            [IP_LABEL],
        )


def profile_version(profile: CompanyProfile, overrides: Any = None) -> str:
    payload = profile.model_dump(mode="json", exclude={"profile_version"})
    raw = json.dumps({"p": payload, "o": overrides}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _mix_features(
    taxonomy: Taxonomy,
    mix: list[IndustryShare],
    coverage: float,
    prior: dict[str, float],
    key: str,
    label_ru: str,
) -> list[Feature]:
    feats: list[Feature] = []
    if mix and coverage > 0:
        for s in mix:
            feats.append(
                Feature(
                    key=f"{key}.{s.industry_id}",
                    label=f"{label_ru}: {s.name}",
                    value=f"{pct(s.share_total)} (данные по {pct(coverage)} платежей)",
                    source="data",
                )
            )
    else:
        for industry_id, share in sorted(prior.items(), key=lambda kv: -kv[1])[:MIX_TOP]:
            feats.append(
                Feature(
                    key=f"{key}.{industry_id}",
                    label=f"{label_ru}: {taxonomy.industry(industry_id).name}",
                    value=f"типично для отрасли ≈ {pct(share)}",
                    source="prior",
                )
            )
    return feats


def make_features(
    taxonomy: Taxonomy,
    p: CompanyProfile,
    *,
    group_size: int = 1,
    override_fields: set[str] | None = None,
) -> list[Feature]:
    overrides = override_fields or set()
    feats: list[Feature] = []
    feats.append(
        Feature(
            key="industry.main",
            label="Основная отрасль",
            value=f"{p.industry_name}" + (f" ({p.okved})" if p.okved else ""),
            source="override" if "industry_id" in overrides else "data",
        )
    )
    for sec in p.secondary_industry_ids:
        feats.append(
            Feature(
                key=f"industry.secondary.{sec}",
                label="Доп. отрасль",
                value=taxonomy.industry(sec).name,
                source="data",
            )
        )
    if p.region_name:
        feats.append(Feature(key="region", label="Регион", value=p.region_name, source="data"))
    feats.append(Feature(key="revenue", label="Выручка", value=BUCKET_RU[p.revenue_bucket], source="data"))
    for code, info in p.products.items():
        if info.has:
            feats.append(
                Feature(
                    key=f"products.{code}",
                    label="Продукт",
                    value=f"{PRODUCT_NAMES.get(code, code)} в Альфа-Банке",
                    source="override" if "products" in overrides else "data",
                )
            )
    for v in p.ved:
        if v.country_iso2:
            feats.append(
                Feature(
                    key=f"ved.country.{v.country_iso2}",
                    label="ВЭД",
                    value=f"{v.country_name} ({DIRECTION_RU[v.direction]})",
                    source="override" if "ved" in overrides else "data",
                )
            )
    prior_s = taxonomy.typical_suppliers(p.industry_id)
    prior_b = taxonomy.typical_buyers(p.industry_id)
    feats += _mix_features(
        taxonomy, p.suppliers_mix, p.coverage.get("supply", 0.0), prior_s, "suppliers", "Закупки у отрасли"
    )
    feats += _mix_features(
        taxonomy, p.buyers_mix, p.coverage.get("demand", 0.0), prior_b, "buyers", "Продажи отрасли"
    )
    feats.append(
        Feature(
            key="coverage.supply",
            label="Покрытие данных о поставщиках",
            value=pct(p.coverage.get("supply", 0.0)),
            source="data",
        )
    )
    feats.append(
        Feature(
            key="coverage.demand",
            label="Покрытие данных о покупателях",
            value=pct(p.coverage.get("demand", 0.0)),
            source="data",
        )
    )
    for f in p.factor_exposure:
        feats.append(
            Feature(
                key=f"factor.{f.factor_id}",
                label=f"Чувствительность: {f.name}",
                value=f"{exposure_level(f.exposure)} ({', '.join(f.reasons[:3])})",
                source="data",
            )
        )
    if p.group_id and group_size > 1:
        feats.append(Feature(key="group", label="Группа", value="Входит в группу компаний", source="data"))
    if p.notes:
        feats.append(Feature(key="override.notes", label="Уточнено вами", value=p.notes, source="override"))
    return feats


def finalize_profile(
    taxonomy: Taxonomy,
    p: CompanyProfile,
    *,
    group_size: int = 1,
    override_fields: set[str] | None = None,
    overrides_payload: Any = None,
) -> CompanyProfile:
    """Пересчитать факторы и признаки и поставить версию. Используется при сборке и после правок."""
    p.factor_exposure = compute_factors(
        taxonomy,
        industry_id=p.industry_id,
        secondary_industry_ids=p.secondary_industry_ids,
        products={code for code, info in p.products.items() if info.has},
        ved=p.ved,
        top_buyer_share=p.top_buyer_share,
    )
    p.features = make_features(taxonomy, p, group_size=group_size, override_fields=override_fields)
    p.profile_version = ""
    p.profile_version = profile_version(p, overrides_payload)
    return p


def build_profiles(conn: duckdb.DuckDBPyConnection, ctx: BuildContext) -> int:
    tax = ctx.taxonomy
    mask_individuals(conn)
    companies = conn.execute("""
        SELECT c.company_id, c.inn, c.name, c.okved, c.okved_secondary, c.region_code, c.region_name,
               c.revenue_rub, c.is_client, c.group_id,
               (SELECT count(*) FROM companies g WHERE g.group_id = c.group_id) AS group_size
        FROM companies c JOIN target_companies USING (company_id)
        ORDER BY c.company_id
    """).fetchall()
    products: dict[str, dict[str, ProductInfo]] = defaultdict(dict)
    for cid, code, amount in conn.execute(
        "SELECT company_id, product_code, max(amount_rub) FROM company_products "
        "WHERE company_id IN (SELECT company_id FROM target_companies) GROUP BY 1, 2"
    ).fetchall():
        products[cid][code] = ProductInfo(has=True, amount_rub=amount)
    ved: dict[str, list[VedEntry]] = defaultdict(list)
    for cid, raw, iso2, direction in conn.execute(
        "SELECT company_id, country_raw, country_iso2, direction FROM company_ved "
        "WHERE company_id IN (SELECT company_id FROM target_companies) ORDER BY company_id, country_raw"
    ).fetchall():
        country = tax.countries.get(iso2) if iso2 else None
        ved[cid].append(
            VedEntry(
                country_iso2=iso2,
                country_name=country_display(tax, iso2, raw),
                direction=direction,
                currencies=list(country.currencies) if country else [],
            )
        )
    mixes: dict[tuple[str, str], list[IndustryShare]] = defaultdict(list)
    for cid, direction, industry_id, share_known, share_total, n in conn.execute(
        "SELECT company_id, direction, industry_id, share_known, share_total, n_counterparties "
        "FROM flows_by_industry WHERE industry_id <> 'unknown' ORDER BY company_id, direction, share_known DESC, industry_id"
    ).fetchall():
        if len(mixes[(cid, direction)]) < MIX_TOP:
            mixes[(cid, direction)].append(
                IndustryShare(
                    industry_id=industry_id,
                    name=tax.industry(industry_id).name,
                    share=round(share_known or 0.0, 6),
                    share_total=round(share_total or 0.0, 6),
                    n_counterparties=n,
                )
            )
    coverage = {
        (cid, d): cov or 0.0
        for cid, d, cov in conn.execute("SELECT company_id, direction, coverage FROM coverage").fetchall()
    }
    top_buyer = dict(
        conn.execute(
            "SELECT company_id, share FROM top_counterparties WHERE direction = 'in' AND rank = 1"
        ).fetchall()
    )
    direction_unknown = bool(ctx.meta.get("direction_unknown"))

    rows = []
    for (
        cid,
        inn,
        name,
        okved,
        secondary,
        region_code,
        region_name,
        revenue,
        is_client,
        group_id,
        gsize,
    ) in companies:
        industry_id = tax.match_okved(okved)
        sec_ids = [
            s
            for s in dict.fromkeys(tax.match_okved(o) for o in (secondary or []))
            if s not in (UNKNOWN, industry_id)
        ]
        profile = CompanyProfile(
            company_id=cid,
            name=name,
            inn=inn,
            okved=okved,
            industry_id=industry_id,
            industry_name=tax.industry(industry_id).name,
            secondary_industry_ids=sec_ids,
            region_code=region_code,
            region_name=region_name,
            revenue_rub=revenue,
            revenue_bucket=revenue_bucket(revenue),
            is_client=bool(is_client),
            group_id=group_id,
            products=dict(sorted(products.get(cid, {}).items())),
            ved=ved.get(cid, []),
            suppliers_mix=mixes.get((cid, "out"), []),
            buyers_mix=mixes.get((cid, "in"), []),
            coverage={
                "supply": round(coverage.get((cid, "out"), 0.0), 6),
                "demand": round(coverage.get((cid, "in"), 0.0), 6),
            },
            direction_unknown=direction_unknown,
            top_buyer_share=round(top_buyer[cid], 6) if cid in top_buyer else None,
            factor_exposure=[],
            features=[],
            profile_version="",
            data_profile=ctx.mapping.profile,
        )
        finalize_profile(tax, profile, group_size=gsize)
        rows.append((cid, profile.model_dump_json(), profile.profile_version, gsize))
    conn.execute(
        "CREATE TABLE profiles (company_id VARCHAR PRIMARY KEY, profile_json VARCHAR, profile_version VARCHAR, group_size INTEGER)"
    )
    if rows:
        conn.executemany("INSERT INTO profiles VALUES (?, ?, ?, ?)", rows)
    conn.execute(
        "CREATE TABLE company_factors (company_id VARCHAR, factor_id VARCHAR, exposure DOUBLE, sign INTEGER, reasons VARCHAR)"
    )
    factor_rows = []
    for cid, pjson, _, _ in rows:
        prof = CompanyProfile.model_validate_json(pjson)
        for f in prof.factor_exposure:
            factor_rows.append(
                (cid, f.factor_id, f.exposure, f.sign, json.dumps(f.reasons, ensure_ascii=False))
            )
    if factor_rows:
        conn.executemany("INSERT INTO company_factors VALUES (?, ?, ?, ?, ?)", factor_rows)
    return len(rows)


# ── чтение профилей с правками ──
class ProfileStore:
    """Профили из DuckDB (только чтение) с наложенными правками из SQLite. Кеш в памяти процесса."""

    def __init__(
        self,
        duck: DuckReader,
        overrides: ProfileOverridesRepo,
        taxonomy: Taxonomy,
        demo_ids: list[str] | None = None,
    ):
        self.duck = duck
        self.overrides = overrides
        self.taxonomy = taxonomy
        self.demo_ids = list(demo_ids or [])
        self._cache: dict[str, CompanyProfile] = {}
        self._base: dict[str, tuple[CompanyProfile, int]] = {}
        self._lock = threading.Lock()

    def _load_base(self, company_id: str) -> tuple[CompanyProfile, int]:
        cached = self._base.get(company_id)
        if cached is not None:
            return cached
        rows = self.duck.rows(
            "SELECT profile_json, group_size FROM profiles WHERE company_id = ?", [company_id]
        )
        if not rows:
            raise NotFoundError("Компания не найдена", {"company_id": company_id})
        base = CompanyProfile.model_validate_json(rows[0]["profile_json"])
        result = (base, int(rows[0]["group_size"] or 1))
        self._base[company_id] = result
        return result

    def get(self, company_id: str) -> CompanyProfile:
        with self._lock:
            cached = self._cache.get(company_id)
            if cached is not None:
                return cached
            base, group_size = self._load_base(company_id)
            profile = self.apply_overrides(base, self.overrides.list(company_id), group_size=group_size)
            self._cache[company_id] = profile
            return profile

    def exists(self, company_id: str) -> bool:
        try:
            self._load_base(company_id)
        except NotFoundError:
            return False
        return True

    def invalidate(self, company_id: str | None = None) -> None:
        with self._lock:
            if company_id is None:
                self._cache.clear()
            else:
                self._cache.pop(company_id, None)

    def list_targets(self) -> list[CompanySummary]:
        rows = self.duck.rows("SELECT profile_json FROM profiles ORDER BY company_id")
        demo = set(self.demo_ids)
        items = []
        for r in rows:
            p = CompanyProfile.model_validate_json(r["profile_json"])
            items.append(
                CompanySummary(
                    company_id=p.company_id,
                    name=p.name,
                    industry_id=p.industry_id,
                    industry_name=p.industry_name,
                    region_name=p.region_name,
                    revenue_bucket=p.revenue_bucket,
                    is_client=p.is_client,
                    is_demo=p.company_id in demo,
                )
            )
        order = {cid: i for i, cid in enumerate(self.demo_ids)}
        items.sort(key=lambda s: (0 if s.is_demo else 1, order.get(s.company_id, 0), s.company_id))
        return items

    def company_ids(self) -> list[str]:
        return [
            r["company_id"] for r in self.duck.rows("SELECT company_id FROM profiles ORDER BY company_id")
        ]

    def apply_overrides(
        self, base: CompanyProfile, overrides: list[Override], *, group_size: int = 1
    ) -> CompanyProfile:
        if not overrides:
            return base
        p = base.model_copy(deep=True)
        fields: set[str] = set()
        for o in overrides:
            if o.field == "industry_id" and o.value in self.taxonomy.industries:
                p.industry_id = o.value
                p.industry_name = self.taxonomy.industry(o.value).name
                fields.add("industry_id")
            elif o.field == "ved" and isinstance(o.value, list):
                entries = []
                for item in o.value:
                    iso2 = str(item.get("country_iso2", "")).upper()
                    country = self.taxonomy.countries.get(iso2)
                    if country is None:
                        continue
                    entries.append(
                        VedEntry(
                            country_iso2=iso2,
                            country_name=country_display(self.taxonomy, iso2, iso2),
                            direction=item.get("direction", "unknown"),
                            currencies=list(country.currencies),
                        )
                    )
                p.ved = entries
                fields.add("ved")
            elif o.field == "products" and isinstance(o.value, dict):
                for code, has in o.value.items():
                    if code not in PRODUCT_NAMES:
                        continue
                    current = p.products.get(code)
                    p.products[code] = ProductInfo(
                        has=bool(has), amount_rub=current.amount_rub if current else None
                    )
                p.products = dict(sorted(p.products.items()))
                fields.add("products")
            elif o.field == "notes" and isinstance(o.value, str):
                p.notes = o.value.strip() or None
                fields.add("notes")
        payload = [{"field": o.field, "value": o.value} for o in overrides]
        return finalize_profile(
            self.taxonomy, p, group_size=group_size, override_fields=fields, overrides_payload=payload
        )
