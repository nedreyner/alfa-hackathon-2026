"""SQL полнотекстового поиска по новостям и аналитике (FTS5, bm25)."""

from __future__ import annotations

from typing import Any

import orjson

from alfa_insight.db.sqlite import SqliteDB


class SearchStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def news(
        self, match: str, *, since: str, company_id: str | None, industry_ids: list[str] | None, limit: int
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT n.id, n.event_id, n.title, n.publisher, n.published_at, n.url,
                   COALESCE(t.summary, substr(n.body, 1, 300)) AS snippet,
                   bm25(news_fts, 3.0, 1.0) AS rank
            FROM news_fts
            JOIN news n ON n.id = news_fts.rowid
            LEFT JOIN news_tags t ON t.news_id = n.id
            WHERE news_fts MATCH ?
              AND n.published_at >= ?
              AND n.status IN ('tagged', 'clustered')
              AND (n.origin <> 'user' OR n.owner_company_id = ?)
              AND (? OR EXISTS (
                    SELECT 1 FROM news_industries ni
                    WHERE ni.news_id = n.id AND ni.industry_id IN (SELECT value FROM json_each(?))))
            ORDER BY rank
            LIMIT ?
        """
        no_filter = not industry_ids
        rows = self.db.query(
            sql,
            (
                match,
                since,
                company_id or "",
                int(no_filter),
                orjson.dumps(industry_ids or []).decode(),
                limit,
            ),
        )
        return [dict(r) for r in rows]

    def research(self, match: str, *, limit: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT c.id, c.source_id, c.page, c.kind, c.heading, c.text, d.title, d.published_at,
                   bm25(research_fts, 2.0, 1.0) AS rank
            FROM research_fts
            JOIN research_chunks c ON c.id = research_fts.rowid
            JOIN research_docs d ON d.id = c.doc_id
            WHERE research_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match, limit),
        )
        return [dict(r) for r in rows]

    def research_items(self, chunk_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
        if not chunk_ids:
            return {}
        marks = ",".join("?" * len(chunk_ids))
        out: dict[int, list[dict[str, Any]]] = {i: [] for i in chunk_ids}
        for r in self.db.query(
            f"SELECT chunk_id, kind, statement, industries_json, factors_json FROM research_items WHERE chunk_id IN ({marks}) ORDER BY id",
            chunk_ids,
        ):
            out[r["chunk_id"]].append(
                {
                    "kind": r["kind"],
                    "statement": r["statement"],
                    "industries": orjson.loads(r["industries_json"]),
                    "factors": orjson.loads(r["factors_json"]),
                }
            )
        return out

    def events(self, match: str, *, since: str, company_id: str | None, limit: int) -> list[dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT e.id, e.title, e.summary, e.last_seen_at, bm25(events_fts, 3.0, 1.0) AS rank
            FROM events_fts JOIN events e ON e.id = events_fts.rowid
            WHERE events_fts MATCH ? AND e.last_seen_at >= ?
              AND (e.visibility = 'public' OR e.owner_company_id = ?)
            ORDER BY rank LIMIT ?
            """,
            (match, since, company_id or "", limit),
        )
        return [dict(r) for r in rows]
