"""Экспозиция компании к макрофакторам по правилам docs/03-data.md §6.4.

Итог по фактору — `min(1, сумма вкладов)`, знак — у правила с наибольшим вкладом. Одна и та же функция
считает факторы при сборке DuckDB и после пользовательских правок профиля.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from alfa_insight.data.models import FactorExposure, VedEntry
from alfa_insight.reference.taxonomy import Taxonomy

TRACKED_CURRENCIES = ("USD", "EUR", "CNY", "TRY", "AED", "INR", "KZT")
GENERAL_FACTORS = ("tax_burden", "labor_costs", "inflation", "payment_discipline")
MIN_EXPOSURE = 0.15
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}
DIRECTION_RU = {"import": "импорт", "export": "экспорт", "unknown": "направление не указано"}


@dataclass
class _Contribution:
    value: float
    sign: int
    reason: str


def compute_factors(
    taxonomy: Taxonomy,
    *,
    industry_id: str,
    secondary_industry_ids: list[str],
    products: set[str],
    ved: list[VedEntry],
    top_buyer_share: float | None,
) -> list[FactorExposure]:
    contrib: dict[str, list[_Contribution]] = defaultdict(list)

    def add(factor_id: str, value: float, sign: int, reason: str) -> None:
        contrib[factor_id].append(_Contribution(value, sign, reason))

    main = taxonomy.industry(industry_id)
    for factor_id, (weight, sign) in main.factor_sensitivity.items():
        add(factor_id, weight, sign, f"отрасль: {main.name}")
    for sec_id in secondary_industry_ids:
        sec = taxonomy.industries.get(sec_id)
        if sec is None:
            continue
        for factor_id, (weight, sign) in sec.factor_sensitivity.items():
            add(factor_id, weight * 0.5, sign, f"доп. отрасль: {sec.name}")

    add("key_rate", 0.2, -1, "общий фактор")
    if "credit" in products:
        add("key_rate", 0.5, -1, "есть кредит")
        add("credit_conditions", 0.4, -1, "есть кредит")
    if "leasing" in products:
        add("key_rate", 0.3, -1, "есть лизинг")

    if ved:
        countries = [(v, taxonomy.countries.get(v.country_iso2) if v.country_iso2 else None) for v in ved]
        for entry, country in countries:
            label = f"ВЭД: {entry.country_name} ({DIRECTION_RU[entry.direction]})"
            currencies = list(country.currencies) if country else list(entry.currencies)
            tracked = [c for c in currencies if c in TRACKED_CURRENCIES]
            weight_mult = 1.0
            if currencies and not tracked:
                tracked, weight_mult = ["USD"], 0.5
            for cur in tracked:
                if entry.direction == "export":
                    add(f"fx_{cur.lower()}", 0.5 * weight_mult, 1, label)
                else:
                    add(f"fx_{cur.lower()}", 0.7 * weight_mult, -1, label)
        add("sanctions", 0.4, -1, "ВЭД")
        scrutinized = [c for _, c in countries if c and LEVEL_ORDER[c.sanctions_scrutiny] >= 1]
        if scrutinized:
            add("sanctions", 0.2, -1, "ВЭД со странами повышенного внимания")
        frictions = [c.payment_friction for _, c in countries if c]
        names = ", ".join(sorted({e.country_name for e, _ in countries}))
        if "high" in frictions:
            add("cross_border_payments", 0.6, -1, f"платежи за рубеж: {names}")
        elif "medium" in frictions:
            add("cross_border_payments", 0.4, -1, f"платежи за рубеж: {names}")
        if any(e.direction in ("import", "unknown") for e, _ in countries):
            add("customs_tariffs", 0.6, -1, "импорт")
        if any(e.direction == "export" for e, _ in countries):
            add("customs_tariffs", 0.3, -1, "экспорт")
        add("logistics", 0.4, -1, "ВЭД")

    add("tax_burden", 0.3, -1, "общий фактор")
    add("labor_costs", 0.2, -1, "общий фактор")
    add("inflation", 0.2, -1, "общий фактор")
    add("payment_discipline", 0.2, -1, "общий фактор")
    if top_buyer_share is not None and top_buyer_share > 0.2:
        add(
            "payment_discipline",
            0.3,
            -1,
            f"концентрация покупателей: {round(top_buyer_share * 100)}% у одного",
        )

    result: list[FactorExposure] = []
    for factor_id, items in contrib.items():
        factor = taxonomy.factors.get(factor_id)
        if factor is None:
            continue
        exposure = min(1.0, sum(i.value for i in items))
        if exposure < MIN_EXPOSURE and factor_id not in GENERAL_FACTORS:
            continue
        strongest = max(items, key=lambda i: i.value)
        reasons = list(dict.fromkeys(i.reason for i in items))
        result.append(
            FactorExposure(
                factor_id=factor_id,
                name=factor.name,
                exposure=round(exposure, 4),
                sign=1 if strongest.sign > 0 else -1,
                reasons=reasons,
            )
        )
    result.sort(key=lambda f: (-f.exposure, f.factor_id))
    return result


def exposure_level(exposure: float) -> str:
    return "высокая" if exposure >= 0.7 else "средняя" if exposure >= 0.4 else "низкая"
