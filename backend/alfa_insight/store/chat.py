"""Таблица `chat_messages`: треды чата по инсайту (docs/08-agent.md §13)."""

from __future__ import annotations

import json
from typing import Any

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now


def _row(r: Any) -> dict[str, Any]:
    d = dict(r)
    d["content"] = json.loads(d.pop("content_json"))
    return d


class ChatStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def add(
        self,
        *,
        thread_id: str,
        insight_id: str,
        company_id: str,
        session_id: str,
        role: str,
        content: dict[str, Any],
        run_id: str | None = None,
    ) -> int:
        cur = self.db.execute(
            "INSERT INTO chat_messages(thread_id, insight_id, company_id, session_id, role, content_json, run_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                thread_id,
                insight_id,
                company_id,
                session_id,
                role,
                json.dumps(content, ensure_ascii=False),
                run_id,
                to_iso(utc_now()),
            ),
        )
        return int(cur.lastrowid or 0)

    def get(self, message_id: int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM chat_messages WHERE id = ?", (message_id,))
        return _row(row) if row else None

    def thread(self, thread_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM chat_messages WHERE thread_id = ? ORDER BY id LIMIT ?", (thread_id, limit)
        )
        return [_row(r) for r in rows]

    def thread_owner(self, thread_id: str) -> tuple[str, str, str] | None:
        """(insight_id, company_id, session_id) первого сообщения треда."""
        row = self.db.query_one(
            "SELECT insight_id, company_id, session_id FROM chat_messages WHERE thread_id = ? ORDER BY id LIMIT 1",
            (thread_id,),
        )
        return (row["insight_id"], row["company_id"], row["session_id"]) if row else None

    def last_thread(self, insight_id: str, session_id: str) -> str | None:
        return self.db.scalar(  # type: ignore[no-any-return]
            "SELECT thread_id FROM chat_messages WHERE insight_id = ? AND session_id = ? ORDER BY id DESC LIMIT 1",
            (insight_id, session_id),
        )
