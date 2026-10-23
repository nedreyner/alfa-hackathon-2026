"""Лемматизация pymorphy3 для FTS, кластеризации и словарей (docs/06-ingestion-search.md §5)."""

from __future__ import annotations

import re
import threading
from functools import lru_cache
from pathlib import Path

import pymorphy3

from alfa_insight.text.normalize import tokenize

_CYRILLIC = re.compile(r"[а-я]")
_lock = threading.Lock()
_analyzer: pymorphy3.MorphAnalyzer | None = None


def _morph() -> pymorphy3.MorphAnalyzer:
    global _analyzer
    with _lock:
        if _analyzer is None:
            _analyzer = pymorphy3.MorphAnalyzer(lang="ru")
        return _analyzer


@lru_cache(maxsize=200_000)
def lemma(token: str) -> str:
    if not _CYRILLIC.search(token):
        return token
    return _morph().parse(token)[0].normal_form.replace("ё", "е")


def load_stopwords(path: Path) -> frozenset[str]:
    words = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            words.append(line.replace("ё", "е"))
    return frozenset(words)


_DEFAULT_STOPWORDS = Path(__file__).resolve().parents[3] / "data" / "reference" / "stopwords_ru.txt"


class Lemmatizer:
    def __init__(self, stopwords: frozenset[str] | None = None):
        if stopwords is None:
            stopwords = load_stopwords(_DEFAULT_STOPWORDS) if _DEFAULT_STOPWORDS.exists() else frozenset()
        self.stopwords = stopwords

    def lemmatize(self, text: str | None) -> list[str]:
        out = []
        for tok in tokenize(text):
            lem = lemma(tok)
            if len(lem) <= 1 or lem in self.stopwords:
                continue
            out.append(lem)
        return out

    def lemmas_str(self, text: str | None) -> str:
        return " ".join(self.lemmatize(text))


_default: Lemmatizer | None = None


def get_lemmatizer() -> Lemmatizer:
    global _default
    if _default is None:
        _default = Lemmatizer()
    return _default


def lemmatize(text: str | None) -> list[str]:
    return get_lemmatizer().lemmatize(text)


def lemmas_str(text: str | None) -> str:
    return get_lemmatizer().lemmas_str(text)
