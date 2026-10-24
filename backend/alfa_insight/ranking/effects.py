"""Матрица «канал × эффект → направление, сила, механизм» и правила направления (docs/07-ranking.md §3, §8)."""

from __future__ import annotations

from collections.abc import Iterable

from alfa_insight.ranking.models import Direction
from alfa_insight.reference.models import MatrixCell
from alfa_insight.reference.taxonomy import Taxonomy

EFFECT_SHORT = {
    "prices_up": "цены растут",
    "prices_down": "цены снижаются",
    "demand_up": "спрос растёт",
    "demand_down": "спрос падает",
    "supply_down": "предложение сокращается",
    "supply_up": "предложение растёт",
    "costs_up": "издержки растут",
    "costs_down": "издержки снижаются",
    "regulation_tighter": "регулирование жёстче",
    "support_measures": "господдержка",
}
DIRECTION_RU = {"risk": "риск", "opportunity": "возможность", "mixed": "смешанное влияние"}


def cell(tax: Taxonomy, channel: str, effect: str) -> MatrixCell:
    return tax.matrix_cell(channel, effect)


def factor_direction(event_direction: int, exposure_sign: int) -> Direction:
    """d·σ > 0 → возможность, иначе риск (docs/03-data.md §5.2)."""
    return "opportunity" if event_direction * exposure_sign > 0 else "risk"


def sgn(direction: Direction) -> int:
    return {"opportunity": 1, "risk": -1, "mixed": 0}[direction]


def combine(contribs: Iterable[tuple[float, Direction]], mixed_ratio: float) -> Direction:
    items = list(contribs)
    total = sum(c for c, _ in items)
    signed = sum(c * sgn(d) for c, d in items)
    if total == 0 or abs(signed) < mixed_ratio * total:
        return "mixed"
    return "risk" if signed < 0 else "opportunity"
