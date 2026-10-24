"""Построение запроса FTS5 по леммам (docs/06-ingestion-search.md §13.1, ADR-11)."""

from __future__ import annotations

from alfa_insight.text.lemmatizer import lemmatize


def build_match(query: str, max_terms: int = 16) -> str | None:
    """Леммы без стоп-слов, уникальные, в порядке появления; каждая в кавычках, через OR."""
    terms: list[str] = []
    for lem in lemmatize(query):
        if lem not in terms:
            terms.append(lem)
        if len(terms) >= max_terms:
            break
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)
