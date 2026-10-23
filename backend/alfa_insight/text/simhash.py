"""simhash64 по леммам и шинглам из трёх лемм (docs/06-ingestion-search.md §7).

Только шинглы на заметках в 100–300 лемм дают 4–10 бит разницы на перепубликации с другим вступлением;
вместе с отдельными леммами — 2 бита, а у разных новостей на одну тему — больше 20.
"""

from __future__ import annotations

import hashlib
from collections import Counter

BITS = 64
SHINGLE = 3


def _hash(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode(), digest_size=8).digest(), "big")


def simhash(lemmas: list[str]) -> int:
    if not lemmas:
        return 0
    shingles = (
        [" ".join(lemmas[i : i + SHINGLE]) for i in range(len(lemmas) - SHINGLE + 1)]
        if len(lemmas) >= SHINGLE
        else [" ".join(lemmas)]
    )
    weights = Counter(shingles) + Counter(lemmas)
    vector = [0] * BITS
    for sh, w in weights.items():
        h = _hash(sh)
        for bit in range(BITS):
            vector[bit] += w if (h >> bit) & 1 else -w
    value = 0
    for bit in range(BITS):
        if vector[bit] > 0:
            value |= 1 << bit
    return value


def hamming(a: int, b: int) -> int:
    return ((a ^ b) & ((1 << BITS) - 1)).bit_count()


def to_signed(value: int) -> int:
    """SQLite хранит знаковый int64."""
    return value - (1 << 64) if value >= (1 << 63) else value


def from_signed(value: int) -> int:
    return value + (1 << 64) if value < 0 else value
