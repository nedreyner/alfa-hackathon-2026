"""Аналитика Альфа-Банка: документы, чанки, элементы, FTS (docs/03-data.md §9)."""

from __future__ import annotations

from typing import Any

import orjson

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now


class ResearchStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def doc_by_slug(self, slug: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM research_docs WHERE slug = ?", (slug,))
        return dict(row) if row else None

    def docs(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM research_docs ORDER BY published_at DESC, id")]

    def delete_doc(self, doc_id: int) -> None:
        with self.db.tx():
            chunk_ids = [
                r["id"] for r in self.db.query("SELECT id FROM research_chunks WHERE doc_id = ?", (doc_id,))
            ]
            for cid in chunk_ids:
                self.db.execute("DELETE FROM research_fts WHERE rowid = ?", (cid,))
            self.db.execute("DELETE FROM research_docs WHERE id = ?", (doc_id,))

    def create_doc(
        self,
        *,
        slug: str,
        title: str,
        published_at: str | None,
        file_name: str,
        sha256: str,
        pages: int,
        url: str | None,
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO research_docs(slug, title, published_at, file_name, sha256, pages, url, status, processed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'parsed', ?)",
            (slug, title, published_at, file_name, sha256, pages, url, to_iso(utc_now())),
        )
        return int(cur.lastrowid or 0)

    def set_doc_status(self, doc_id: int, status: str) -> None:
        self.db.execute(
            "UPDATE research_docs SET status = ?, processed_at = ? WHERE id = ?",
            (status, to_iso(utc_now()), doc_id),
        )

    def add_chunk(
        self,
        doc_id: int,
        *,
        source_id: str,
        page: int,
        chunk_no: int,
        kind: str,
        heading: str | None,
        text: str,
        heading_lemmas: str,
        text_lemmas: str,
    ) -> int:
        with self.db.tx():
            cur = self.db.execute(
                "INSERT INTO research_chunks(doc_id, source_id, page, chunk_no, kind, heading, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (doc_id, source_id, page, chunk_no, kind, heading, text),
            )
            chunk_id = int(cur.lastrowid or 0)
            self.db.execute(
                "INSERT INTO research_fts(rowid, heading_lemmas, text_lemmas) VALUES (?, ?, ?)",
                (chunk_id, heading_lemmas, text_lemmas),
            )
        return chunk_id

    def add_items(self, chunk_id: int, items: list[dict[str, Any]]) -> None:
        self.db.executemany(
            "INSERT INTO research_items(chunk_id, kind, statement, indicator, value, unit, period, industries_json, "
            "factors_json, confidence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    chunk_id,
                    it["kind"],
                    it["statement"],
                    it.get("indicator"),
                    it.get("value"),
                    it.get("unit"),
                    it.get("period"),
                    orjson.dumps(it.get("industries", [])).decode(),
                    orjson.dumps(it.get("factors", [])).decode(),
                    it["confidence"],
                )
                for it in items
            ],
        )

    def chunks(self, doc_id: int) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.query(
                "SELECT * FROM research_chunks WHERE doc_id = ? ORDER BY page, chunk_no", (doc_id,)
            )
        ]

    def chunk_by_source(self, source_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT c.*, d.title AS doc_title, d.published_at AS doc_date, d.url AS doc_url, d.slug "
            "FROM research_chunks c JOIN research_docs d ON d.id = c.doc_id WHERE c.source_id = ?",
            (source_id,),
        )
        return dict(row) if row else None

    def items_for_chunk(self, chunk_id: int) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM research_items WHERE chunk_id = ? ORDER BY id", (chunk_id,))
        out = []
        for r in rows:
            d = dict(r)
            d["industries"] = orjson.loads(d.pop("industries_json"))
            d["factors"] = orjson.loads(d.pop("factors_json"))
            out.append(d)
        return out

    def counts(self) -> dict[str, int]:
        return {
            t: int(self.db.scalar(f"SELECT count(*) FROM {t}") or 0)
            for t in ("research_docs", "research_chunks", "research_items")
        }
