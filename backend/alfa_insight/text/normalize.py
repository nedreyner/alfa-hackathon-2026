"""Нормализация текста и URL (docs/06-ingestion-search.md §3, §5)."""

from __future__ import annotations

import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[ \t  -   　]+")
_EMPTY_LINES = re.compile(r"\n\s*\n+")
_TOKEN = re.compile(r"[a-zа-я0-9]+(?:-[a-zа-я0-9]+)*")
TRACKING_PARAMS = {"from", "ref", "yclid", "gclid", "fbclid", "utm_referrer"}
MAX_BODY_CHARS = 20_000
# Управляющие (кроме \t \n \r), невидимые и символы-теги Unicode
_INVISIBLE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u206f\ufeff\U000e0000-\U000e007f]"
)


def count_invisible(text: str) -> int:
    return len(_INVISIBLE.findall(text))


def strip_invisible(text: str) -> str:
    return _INVISIBLE.sub("", text)


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return _TAGS.sub(" ", html.unescape(text))


def normalize_text(text: str | None, *, limit: int | None = None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFC", html.unescape(text))
    value = strip_invisible(value)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = _SPACES.sub(" ", value)
    value = "\n".join(line.strip() for line in value.split("\n"))
    value = _EMPTY_LINES.sub("\n\n", value).strip()
    if limit is not None and len(value) > limit:
        value = value[:limit].rstrip()
    return value


def remove_boilerplate(text: str, phrases: list[str]) -> str:
    """Удалить строки, начинающиеся с шаблонных фраз («Читайте также», «Реклама», …)."""
    lowered = [p.lower() for p in phrases]
    kept = [line for line in text.split("\n") if not any(line.strip().lower().startswith(p) for p in lowered)]
    return "\n".join(kept).strip()


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return _TOKEN.findall(text.lower().replace("ё", "е"))


def normalize_url(url: str | None) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunsplit((scheme, host, path, urlencode(query), ""))
