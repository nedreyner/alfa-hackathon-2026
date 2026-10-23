"""Детерминированный префильтр до LLM (docs/06-ingestion-search.md §6, ADR-10)."""

from __future__ import annotations

from dataclasses import dataclass, field

from alfa_insight.ingest.sources import Source
from alfa_insight.reference.taxonomy import UNKNOWN, Taxonomy
from alfa_insight.text.lemmatizer import Lemmatizer, get_lemmatizer


@dataclass
class PrefilterResult:
    score: float
    passed: bool
    econ_hits: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    category: str = "none"  # allowed | none | rejected | soft


class Prefilter:
    def __init__(self, taxonomy: Taxonomy, *, min_score: float = 3.0, lemmatizer: Lemmatizer | None = None):
        self.lem = lemmatizer or get_lemmatizer()
        lex = taxonomy.prefilter
        self.min_score = min_score
        self.econ = set(lex.econ)
        self.negative = set(lex.negative)
        self.exceptions = {k: set(v) for k, v in lex.negative_exceptions.items()}
        self.industry_keys: dict[str, list[tuple[str, ...]]] = {}
        for ind in taxonomy.industries.values():
            if ind.id == UNKNOWN:
                continue
            keys = []
            for kw in ind.keywords:
                lemmas = tuple(self.lem.lemmatize(kw)) or (kw.lower(),)
                keys.append(lemmas)
            self.industry_keys[ind.id] = keys

    def score(
        self, title: str, body: str | None, categories: list[str], source: Source | None, trust: float
    ) -> PrefilterResult:
        lemmas = self.lem.lemmatize(f"{title}\n{body or ''}")
        lemma_set = set(lemmas)
        joined = " " + " ".join(lemmas) + " "
        res = PrefilterResult(score=0.0, passed=False)
        if source is None or not source.has_category_filter:
            res.score += 2
            res.category = "none"
        elif source.category_allowed(categories):
            res.score += 2
            res.category = "allowed"
        elif categories:
            res.score -= 1 if source.categories_soft else 3
            res.category = "soft" if source.categories_soft else "rejected"
        res.econ_hits = sorted(lemma_set & self.econ)
        res.score += min(4, len(res.econ_hits))
        for iid, keys in self.industry_keys.items():
            if any((k[0] in lemma_set) if len(k) == 1 else (" " + " ".join(k) + " ") in joined for k in keys):
                res.industries.append(iid)
        res.score += min(2, len(res.industries))
        for neg in sorted(lemma_set & self.negative):
            if self.exceptions.get(neg, set()) & lemma_set:
                continue
            res.negative.append(neg)
        res.score -= min(6, 3 * len(res.negative))
        res.passed = res.score >= self.min_score or trust >= 1.0
        return res
