"""Отрасль контрагента по названию: ключевые слова отраслей против слов названия.

До появления лемматизатора (T2.1) — простая нормализация: нижний регистр, `ё` → `е`,
совпадение ключевого слова с началом слова названия. Многословные ключи ищутся подстрокой.
"""

from __future__ import annotations

import re

from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy

_WORD = re.compile(r"[a-zа-я0-9]+")


def name_words(name: str) -> list[str]:
    return _WORD.findall(name.lower().replace("ё", "е"))


def match_name_industry(name: str | None, taxonomy: Taxonomy) -> str | None:
    """Отрасль с наибольшим числом совпавших ключевых слов; ничья или ноль совпадений → None."""
    if not name:
        return None
    words = name_words(name)
    text = " ".join(words)
    best: list[tuple[int, str]] = []
    for ind in taxonomy.industries.values():
        if ind.id == UNKNOWN:
            continue
        hits = 0
        for kw in ind.keywords:
            key = kw.lower().replace("ё", "е")
            if " " in key or "-" in key:
                hits += key.replace("-", " ") in text
            else:
                hits += any(w.startswith(key) for w in words)
        if hits:
            best.append((hits, ind.id))
    if not best:
        return None
    best.sort(reverse=True)
    if len(best) > 1 and best[0][0] == best[1][0]:
        return None
    return best[0][1]
