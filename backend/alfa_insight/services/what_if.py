"""Фича C «Что если»: детерминированный пересчёт чувствительности к ставке и курсу, без LLM (14-backlog.md T5.3).

Сценарий доступен, если среди путей влияния события на компанию есть ставка (`key_rate`, `credit_conditions`)
или курс (`fx_*`). Расчёт — арифметика по данным профиля; результат всегда помечается как оценка ИИ-сервиса.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.agent.schemas import Insight
from alfa_insight.appctx import AppContext
from alfa_insight.data.models import CompanyProfile
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.rankings import RankingStore

RATE_FACTORS = ("key_rate", "credit_conditions")
RATE_LIMIT_PP = 2.0
FX_LIMIT_PCT = 10.0
BILLION = 1_000_000_000
Level = Literal["low", "medium", "high"]


class WhatIfIn(BaseModel):
    rate_delta_pp: float = Field(
        default=0.0, ge=-RATE_LIMIT_PP, le=RATE_LIMIT_PP, description="Изменение ставки, п. п."
    )
    fx_delta_pct: float = Field(
        default=0.0, ge=-FX_LIMIT_PCT, le=FX_LIMIT_PCT, description="Изменение курса, %"
    )
    currency: str | None = Field(
        default=None, max_length=3, description="Валюта сценария курса, например CNY"
    )


class RateScenario(BaseModel):
    key_rate_now: float | None
    key_rate_new: float | None
    debt_rub: float | None  # кредит + лизинг из профиля
    delta_rub_year: float | None  # если весь долг с плавающей ставкой
    share_of_revenue: float | None
    level: Level
    text: str


class FxScenario(BaseModel):
    currency: str
    rate_now: float | None
    rate_new: float | None
    direction: Literal["import", "export", "mixed"]
    delta_rub_per_billion: float  # на каждый 1 млрд ₽ расчётов в валюте
    level: Level
    text: str


class WhatIfOut(BaseModel):
    rate_available: bool
    currencies: list[str]
    rate: RateScenario | None = None
    fx: FxScenario | None = None
    label: str = "Вывод ИИ: оценка"
    disclaimer: str = "Арифметическая оценка по данным профиля: без учёта хеджирования, фиксированных ставок и пересмотра цен."


def _paths_factors(app: AppContext, ins: Insight) -> set[str]:
    row = RankingStore(app.db).get(ins.company_id, ins.event.id, ins.role_generated_for)
    if row is None:
        return set()
    paths = json.loads(row["chain_json"]).get("paths") or []
    return {p["factor_id"] for p in paths if p.get("factor_id")}


def _level(value: float, low: float, high: float) -> Level:
    return "high" if value >= high else "medium" if value >= low else "low"


def _fmt_rub(v: float) -> str:
    a = abs(v)
    if a >= BILLION:
        return f"{a / BILLION:.2f} млрд ₽".replace(".", ",")
    return f"{a / 1_000_000:.0f} млн ₽"


def rate_scenario(profile: CompanyProfile, key_rate: float | None, delta_pp: float) -> RateScenario:
    debt = sum(
        p.amount_rub or 0.0 for k, p in profile.products.items() if k in ("credit", "leasing") and p.has
    )
    new_rate = round(key_rate + delta_pp, 2) if key_rate is not None else None
    if not debt:
        exp = profile.factor("key_rate")
        level = _level(exp.exposure if exp else 0.0, 0.3, 0.7)
        return RateScenario(
            key_rate_now=key_rate, key_rate_new=new_rate, debt_rub=None, delta_rub_year=None, share_of_revenue=None,
            level=level, text="Сумма долга неизвестна: оценка только качественная — по профилю компании.",
        )  # fmt: skip
    delta = debt * delta_pp / 100
    share = abs(delta) / profile.revenue_rub if profile.revenue_rub else None
    if delta_pp == 0:
        text = "Сдвиньте ставку, чтобы увидеть изменение процентных расходов за год."
    else:
        verb = "вырастут" if delta > 0 else "снизятся"
        text = (
            f"Если весь долг ({_fmt_rub(debt)}) с плавающей ставкой, процентные расходы {verb} примерно на "
            f"{_fmt_rub(delta)} в год"
            + (f" — {share * 100:.2f}% выручки".replace(".", ",") if share is not None else "")
            + ". При фиксированной ставке эффект придёт при рефинансировании и новых займах."
        )
    return RateScenario(
        key_rate_now=key_rate, key_rate_new=new_rate, debt_rub=debt, delta_rub_year=round(delta, 2),
        share_of_revenue=round(share, 6) if share is not None else None,
        level=_level(share or 0.0, 0.001, 0.005), text=text,
    )  # fmt: skip


def fx_scenario(
    profile: CompanyProfile, currency: str, rate_now: float | None, delta_pct: float
) -> FxScenario:
    dirs = {v.direction for v in profile.ved if currency in v.currencies}
    direction: Literal["import", "export", "mixed"] = (
        "import" if dirs == {"import"} else "export" if dirs == {"export"} else "mixed"
    )
    exp = profile.factor(f"fx_{currency.lower()}")
    per_billion = BILLION * delta_pct / 100
    rate_new = round(rate_now * (1 + delta_pct / 100), 4) if rate_now is not None else None
    if delta_pct == 0:
        text = "Сдвиньте курс, чтобы увидеть эффект на расчёты в валюте."
    else:
        up = delta_pct > 0
        if direction == "import":
            effect = "дороже" if up else "дешевле"
            text = f"Закупки в {currency} станут {effect}: каждый 1 млрд ₽ платежей — {'+' if up else '−'}{_fmt_rub(per_billion)}."
        elif direction == "export":
            effect = "больше" if up else "меньше"
            text = f"Выручка в {currency} в рублях станет {effect}: каждый 1 млрд ₽ поступлений — {'+' if up else '−'}{_fmt_rub(per_billion)}."
        else:
            text = f"Расчёты в {currency} идут в обе стороны: эффект {_fmt_rub(per_billion)} на 1 млрд ₽ частично взаимно гасится."
    return FxScenario(
        currency=currency, rate_now=rate_now, rate_new=rate_new, direction=direction,
        delta_rub_per_billion=round(per_billion, 2), level=_level(exp.exposure if exp else 0.0, 0.3, 0.7), text=text,
    )  # fmt: skip


def what_if(app: AppContext, ins: Insight, inp: WhatIfIn) -> WhatIfOut:
    factors = _paths_factors(app, ins)
    profile = app.profiles.get(ins.company_id)
    rate_ok = bool(factors & set(RATE_FACTORS))
    currencies = sorted(f.removeprefix("fx_").upper() for f in factors if f.startswith("fx_"))
    macro = MacroStore(app.db)
    out = WhatIfOut(rate_available=rate_ok, currencies=currencies)
    if rate_ok:
        kr = macro.summary("key_rate")
        out.rate = rate_scenario(profile, kr.latest.value if kr else None, inp.rate_delta_pp)
    cur = (inp.currency or "").upper() or (currencies[0] if currencies else None)
    if cur and cur in currencies:
        fx = macro.summary(f"fx_{cur.lower()}")
        out.fx = fx_scenario(profile, cur, fx.latest.value if fx else None, inp.fx_delta_pct)
    return out
