"""Значимые числа в тексте для проверки `numbers_match` (docs/08-agent.md §9.1)."""

from __future__ import annotations

import re
from dataclasses import dataclass

SCALE = {
    "тыс": 1e3,
    "тысяч": 1e3,
    "тысячи": 1e3,
    "млн": 1e6,
    "миллион": 1e6,
    "миллиона": 1e6,
    "миллионов": 1e6,
    "млрд": 1e9,
    "миллиард": 1e9,
    "миллиарда": 1e9,
    "миллиардов": 1e9,
    "трлн": 1e12,
    "триллион": 1e12,
    "триллиона": 1e12,
    "триллионов": 1e12,
}
PERCENT = ("%", "процент", "п.п", "п. п", "пп", "б.п", "б. п", "bp")
CURRENCY = (
    "₽",
    "руб",
    "р.",
    "$",
    "долл",
    "usd",
    "€",
    "евро",
    "eur",
    "юан",
    "cny",
    "¥",
    "лир",
    "рупи",
    "тенге",
    "дирхам",
)

_NUM = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:[   ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<tail>\s*(?:%|[а-яёa-z$€₽¥.]+(?:\s*\.)?)?(?:\s*[а-яёa-z$€₽¥.]+)?)",
    re.I,
)


@dataclass(frozen=True)
class NumberMention:
    value: float
    unit: str | None
    raw: str


def _parse(num: str) -> float:
    return float(re.sub(r"[   ]", "", num).replace(",", "."))


def extract_numbers(text: str | None) -> list[NumberMention]:
    if not text:
        return []
    out: list[NumberMention] = []
    for m in _NUM.finditer(text):
        raw_num = m.group("num")
        tail = (m.group("tail") or "").strip().lower().replace("ё", "е")
        words = tail.replace(".", " . ").split()
        value = _parse(raw_num)
        unit: str | None = None
        scaled = False
        first = words[0].rstrip(".") if words else ""
        if tail.startswith("%") or any(tail.startswith(p) for p in PERCENT):
            unit = "%"
        else:
            if first in SCALE:
                value *= SCALE[first]
                scaled = True
                rest = tail[len(words[0]) :].strip(" .")
                if any(rest.startswith(c) for c in CURRENCY):
                    unit = "rub" if rest.startswith(("₽", "руб", "р.")) else "fx"
                else:
                    unit = "scale"
            elif any(tail.startswith(c) for c in CURRENCY):
                unit = "rub" if tail.startswith(("₽", "руб", "р.")) else "fx"
        has_decimal = bool(re.search(r"[.,]\d", raw_num)) and not re.fullmatch(
            r"\d{1,3}(?:[   ]\d{3})+", raw_num
        )
        is_year = (
            unit is None
            and not scaled
            and not has_decimal
            and raw_num.isdigit()
            and 1990 <= int(raw_num) <= 2100
        )
        significant = unit is not None or scaled or has_decimal or (value >= 100 and not is_year)
        if significant:
            out.append(NumberMention(value=value, unit=unit, raw=m.group(0).strip()))
    return out


def numbers_close(a: float, b: float, tol: float = 0.005) -> bool:
    if a == b:
        return True
    denom = max(abs(a), abs(b))
    return denom > 0 and abs(a - b) / denom <= tol


def number_supported(value: float, candidates: list[float], tol: float = 0.005) -> bool:
    return any(numbers_close(value, c, tol) for c in candidates)
