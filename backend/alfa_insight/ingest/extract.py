"""Полный текст статьи из HTML (docs/06-ingestion-search.md §4)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import trafilatura

from alfa_insight.text.normalize import MAX_BODY_CHARS, normalize_text, remove_boilerplate

MIN_BODY_CHARS = 300


@dataclass
class ExtractedText:
    body: str
    body_source: str  # full | rss_summary | user | seed
    title: str | None = None


def extract_main_text(html: str, url: str | None = None) -> str | None:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
        deduplicate=True,
        output_format="txt",
    )
    return text or None


def extract_title(html: str) -> str | None:
    meta = trafilatura.extract_metadata(html)
    return meta.title if meta is not None and meta.title else None


def clean_body(text: str | None, boilerplate: list[str]) -> str:
    return normalize_text(remove_boilerplate(normalize_text(text), boilerplate), limit=MAX_BODY_CHARS)


def choose_body(
    html: str | None, url: str | None, title: str, rss_summary: str | None, boilerplate: list[str]
) -> ExtractedText:
    """Полный текст, если он длиннее 300 символов; иначе RSS-анонс; иначе заголовок."""
    if html:
        body = clean_body(extract_main_text(html, url), boilerplate)
        if len(body) >= MIN_BODY_CHARS:
            return ExtractedText(body=body, body_source="full", title=extract_title(html))
    summary = clean_body(rss_summary, boilerplate)
    if summary:
        return ExtractedText(body=summary, body_source="rss_summary")
    return ExtractedText(body=normalize_text(title), body_source="rss_summary")


def content_hash(title: str, body: str) -> str:
    return hashlib.sha1((title.lower() + "\n" + body[:5000].lower()).encode("utf-8")).hexdigest()
