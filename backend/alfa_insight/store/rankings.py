"""Таблица `rankings`: скор пары «компания × событие × роль» и сериализованная цепочка."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now


class RankingStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def replace(self, rows: list[dict[str, Any]], *, drop: Sequence[tuple[str, int, str]]) -> None:
        now = to_iso(utc_now())
        with self.db.tx():
            if drop:
                self.db.executemany(
                    "DELETE FROM rankings WHERE company_id = ? AND event_id = ? AND role = ?", drop
                )
            self.db.executemany(
                "INSERT INTO rankings(company_id, event_id, role, score, relevance, rerank_score, direction, impact_level, "
                "chain_preview, components_json, chain_json, profile_version, computed_at) "
                "VALUES (:company_id, :event_id, :role, :score, :relevance, :rerank_score, :direction, :impact_level, "
                ":chain_preview, :components_json, :chain_json, :profile_version, :computed_at) "
                "ON CONFLICT(company_id, event_id, role) DO UPDATE SET score = excluded.score, "
                "relevance = excluded.relevance, rerank_score = excluded.rerank_score, direction = excluded.direction, impact_level = excluded.impact_level, "
                "chain_preview = excluded.chain_preview, components_json = excluded.components_json, "
                "chain_json = excluded.chain_json, profile_version = excluded.profile_version, "
                "computed_at = excluded.computed_at",
                [{"rerank_score": None, **r, "computed_at": now} for r in rows],
            )

    def delete_company(self, company_id: str, keep_event_ids: set[int] | None = None) -> None:
        if keep_event_ids is None:
            self.db.execute("DELETE FROM rankings WHERE company_id = ?", (company_id,))
            return
        rows = self.db.query("SELECT DISTINCT event_id FROM rankings WHERE company_id = ?", (company_id,))
        stale = [(company_id, r["event_id"]) for r in rows if r["event_id"] not in keep_event_ids]
        self.db.executemany("DELETE FROM rankings WHERE company_id = ? AND event_id = ?", stale)

    def get(self, company_id: str, event_id: int, role: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT * FROM rankings WHERE company_id = ? AND event_id = ? AND role = ?",
            (company_id, event_id, role),
        )
        return dict(row) if row else None

    def top(
        self, company_id: str, role: str, *, min_score: float = 0.0, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM rankings WHERE company_id = ? AND role = ? AND score >= ? "
            "ORDER BY score DESC, event_id DESC LIMIT ? OFFSET ?",
            (company_id, role, min_score, limit, offset),
        )
        return [dict(r) for r in rows]

    def count(self, company_id: str | None = None) -> int:
        if company_id:
            return int(
                self.db.scalar("SELECT count(*) FROM rankings WHERE company_id = ?", (company_id,)) or 0
            )
        return int(self.db.scalar("SELECT count(*) FROM rankings") or 0)
