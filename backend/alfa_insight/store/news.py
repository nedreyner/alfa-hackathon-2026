"""Таблица `news` и связанные (теги, FTS). SQL к новостям — только здесь."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Any

import orjson
from pydantic import BaseModel, Field

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now

NEWS_COLUMNS = (
    "source_id, origin, external_id, url, url_hash, title, rss_summary, body, body_source, publisher, trust, "
    "published_at, fetched_at, rss_categories, content_hash, simhash, status, owner_company_id, created_at"
)


def url_hash(url: str | None) -> str | None:
    return hashlib.sha1(url.encode("utf-8")).hexdigest() if url else None


class NewsIn(BaseModel):
    source_id: str
    origin: str  # rss | seed | user
    external_id: str | None = None
    url: str | None = None
    title: str
    rss_summary: str | None = None
    body: str | None = None
    body_source: str | None = None
    publisher: str
    trust: float
    published_at: str
    fetched_at: str
    rss_categories: list[str] = Field(default_factory=list)
    content_hash: str | None = None
    status: str = "new"
    owner_company_id: str | None = None


class NewsRow(BaseModel):
    id: int
    source_id: str
    origin: str
    external_id: str | None
    url: str | None
    title: str
    rss_summary: str | None
    body: str | None
    body_source: str | None
    publisher: str
    trust: float
    published_at: str
    fetched_at: str
    rss_categories: list[str]
    content_hash: str | None
    simhash: int | None
    prefilter_score: float | None
    status: str
    attempts: int
    duplicate_of: int | None
    injection_flags: list[str]
    error: str | None
    event_id: int | None
    owner_company_id: str | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> NewsRow:
        d = dict(row)
        d["rss_categories"] = orjson.loads(d.get("rss_categories") or "[]")
        d["injection_flags"] = orjson.loads(d.get("injection_flags") or "[]")
        return cls.model_validate(d)


class NewsStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    # ── вставка ──
    def insert(self, items: Iterable[NewsIn]) -> list[int]:
        """INSERT OR IGNORE по url_hash и (source_id, external_id). Возвращает id новых строк."""
        new_ids: list[int] = []
        now = to_iso(utc_now())
        with self.db.tx():
            for it in items:
                cur = self.db.execute(
                    f"INSERT OR IGNORE INTO news ({NEWS_COLUMNS}) VALUES ({','.join('?' * 19)})",
                    (
                        it.source_id,
                        it.origin,
                        it.external_id,
                        it.url,
                        url_hash(it.url),
                        it.title,
                        it.rss_summary,
                        it.body,
                        it.body_source,
                        it.publisher,
                        it.trust,
                        it.published_at,
                        it.fetched_at,
                        orjson.dumps(it.rss_categories).decode(),
                        it.content_hash,
                        None,
                        it.status,
                        it.owner_company_id,
                        now,
                    ),
                )
                if cur.rowcount:
                    new_ids.append(int(cur.lastrowid or 0))
        return new_ids

    # ── чтение ──
    def get(self, news_id: int) -> NewsRow | None:
        row = self.db.query_one("SELECT * FROM news WHERE id = ?", (news_id,))
        return NewsRow.from_row(row) if row else None

    def by_url(self, url: str) -> NewsRow | None:
        row = self.db.query_one("SELECT * FROM news WHERE url_hash = ?", (url_hash(url),))
        return NewsRow.from_row(row) if row else None

    def by_external(self, source_id: str, external_id: str) -> NewsRow | None:
        row = self.db.query_one(
            "SELECT * FROM news WHERE source_id = ? AND external_id = ?", (source_id, external_id)
        )
        return NewsRow.from_row(row) if row else None

    def by_status(self, status: str, limit: int = 100, *, newest_first: bool = True) -> list[NewsRow]:
        order = "DESC" if newest_first else "ASC"
        rows = self.db.query(
            f"SELECT * FROM news WHERE status = ? ORDER BY published_at {order}, id {order} LIMIT ?",
            (status, limit),
        )
        return [NewsRow.from_row(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        return {
            r["status"]: r["n"]
            for r in self.db.query("SELECT status, count(*) AS n FROM news GROUP BY status")
        }

    def all_ids(self) -> list[int]:
        return [r["id"] for r in self.db.query("SELECT id FROM news ORDER BY id")]

    # ── обновление стадий ──
    def set_extracted(
        self,
        news_id: int,
        *,
        body: str,
        body_source: str,
        content_hash: str,
        injection_flags: list[str],
        title: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE news SET body = ?, body_source = ?, content_hash = ?, injection_flags = ?, "
            "title = COALESCE(?, title), status = 'extracted', error = NULL WHERE id = ? AND status = 'new'",
            (body, body_source, content_hash, orjson.dumps(injection_flags).decode(), title, news_id),
        )

    def bump_attempt(self, news_id: int, error: str) -> int:
        self.db.execute(
            "UPDATE news SET attempts = attempts + 1, error = ? WHERE id = ?", (error[:500], news_id)
        )
        return int(self.db.scalar("SELECT attempts FROM news WHERE id = ?", (news_id,)) or 0)

    def set_status(self, news_id: int, status: str, **fields: Any) -> None:
        sets = ["status = ?"]
        params: list[Any] = [status]
        for key, value in fields.items():
            sets.append(f"{key} = ?")
            params.append(orjson.dumps(value).decode() if isinstance(value, list | dict) else value)
        params.append(news_id)
        self.db.execute(f"UPDATE news SET {', '.join(sets)} WHERE id = ?", params)

    def update_dates(self, shifts: dict[int, tuple[str, str]]) -> None:
        with self.db.tx():
            for news_id, (published_at, fetched_at) in shifts.items():
                self.db.execute(
                    "UPDATE news SET published_at = ?, fetched_at = ? WHERE id = ?",
                    (published_at, fetched_at, news_id),
                )
