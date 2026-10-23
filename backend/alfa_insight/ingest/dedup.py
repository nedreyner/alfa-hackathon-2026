"""Дедупликация: точный дубль по content_hash и почти дубль по simhash (docs/06-ingestion-search.md §7)."""

from __future__ import annotations

from dataclasses import dataclass

from alfa_insight.text.lemmatizer import Lemmatizer, get_lemmatizer
from alfa_insight.text.simhash import hamming, simhash

SIMHASH_TEXT_CHARS = 3000


@dataclass
class DedupIndex:
    """Недавние simhash (за 72 ч) и хеши содержимого (за 7 дней), загружаются в начале тика."""

    simhashes: list[tuple[int, int]]  # (news_id, simhash без знака)
    content_hashes: dict[str, int]  # content_hash → news_id


class Deduper:
    def __init__(self, max_distance: int = 3, lemmatizer: Lemmatizer | None = None):
        self.max_distance = max_distance
        self.lem = lemmatizer or get_lemmatizer()

    def fingerprint(self, title: str, body: str | None) -> int:
        return simhash(self.lem.lemmatize(f"{title}\n{(body or '')[:SIMHASH_TEXT_CHARS]}"))

    def find_duplicate(
        self, index: DedupIndex, news_id: int, content_hash: str | None, fp: int
    ) -> int | None:
        if content_hash:
            other = index.content_hashes.get(content_hash)
            if other is not None and other != news_id:
                return other
        best: tuple[int, int] | None = None
        for other_id, other_fp in index.simhashes:
            if other_id == news_id:
                continue
            dist = hamming(fp, other_fp)
            if dist <= self.max_distance and (best is None or dist < best[0]):
                best = (dist, other_id)
        return best[1] if best else None

    @staticmethod
    def remember(index: DedupIndex, news_id: int, content_hash: str | None, fp: int) -> None:
        index.simhashes.append((news_id, fp))
        if content_hash:
            index.content_hashes.setdefault(content_hash, news_id)
