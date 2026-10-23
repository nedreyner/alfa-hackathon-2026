"""Отрасль контрагента по названию: ключевые слова отраслей (леммы) против лемм названия.

Слово названия совпадает с ключом, если его лемма начинается с ключа («МеталлТрейд» → «металл»).
Многословные ключи ищутся подстрокой в лемматизированном названии.
"""

from __future__ import annotations

from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy
from alfa_insight.text.lemmatizer import lemma
from alfa_insight.text.normalize import tokenize


def name_words(name: str) -> list[str]:
    return [lemma(t) for t in tokenize(name)]


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
            key = " ".join(lemma(t) for t in tokenize(kw)) or kw.lower()
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
