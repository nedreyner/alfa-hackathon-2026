"""Таблицы `feedback`, `ui_events`, `leads` (docs/09-api.md §4.4, §4.7)."""

from __future__ import annotations

import json
from typing import Any

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now


class FeedbackStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def upsert(
        self, *, insight_id: str, company_id: str, role: str, session_id: str, useful: bool,
        reason: str | None, comment: str | None,
    ) -> dict[str, Any]:  # fmt: skip
        """Одна оценка на (инсайт, сессия): повтор заменяет предыдущую."""
        self.db.execute(
            "INSERT INTO feedback(insight_id, company_id, role, session_id, useful, reason, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(insight_id, session_id) DO UPDATE SET "
            "useful = excluded.useful, reason = excluded.reason, comment = excluded.comment, role = excluded.role, "
            "created_at = excluded.created_at",
            (insight_id, company_id, role, session_id, int(useful), reason, comment, to_iso(utc_now())),
        )
        return self.get(insight_id, session_id)  # type: ignore[return-value]

    def get(self, insight_id: str, session_id: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT useful, reason, comment, created_at FROM feedback WHERE insight_id = ? AND session_id = ?",
            (insight_id, session_id),
        )
        if row is None:
            return None
        return {
            "useful": bool(row["useful"]),
            "reason": row["reason"],
            "comment": row["comment"],
            "created_at": row["created_at"],
        }

    def stats(self) -> dict[str, int]:
        row = self.db.query_one("SELECT count(*) AS n, COALESCE(sum(useful), 0) AS useful FROM feedback")
        return {"total": int(row["n"]), "useful": int(row["useful"])} if row else {"total": 0, "useful": 0}


class UiEventStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def add(
        self, *, session_id: str, company_id: str, type: str, insight_id: str | None, payload: dict[str, Any]
    ) -> None:
        self.db.execute(
            "INSERT INTO ui_events(session_id, company_id, type, insight_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                company_id,
                type,
                insight_id,
                json.dumps(payload, ensure_ascii=False)[:4000],
                to_iso(utc_now()),
            ),
        )

    def counts(self) -> dict[str, int]:
        return {
            r["type"]: r["n"]
            for r in self.db.query("SELECT type, count(*) AS n FROM ui_events GROUP BY type")
        }


class LeadStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def add(
        self,
        *,
        company_id: str,
        session_id: str,
        product_id: str,
        insight_id: str | None,
        comment: str | None,
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO leads(company_id, session_id, product_id, insight_id, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (company_id, session_id, product_id, insight_id, comment, to_iso(utc_now())),
        )
        return int(cur.lastrowid or 0)
