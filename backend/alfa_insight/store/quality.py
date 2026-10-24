"""Запросы онлайн-метрик качества (docs/12-quality.md §6). Только чтение."""

from __future__ import annotations

import json
from typing import Any

from alfa_insight.db.sqlite import SqliteDB


class QualityStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def feedback(self, since: str) -> tuple[int, int, dict[str, int]]:
        row = self.db.query_one(
            "SELECT count(*) AS n, COALESCE(sum(useful), 0) AS u FROM feedback WHERE created_at >= ?",
            (since,),
        )
        reasons = {
            r["reason"] or "none": r["n"]
            for r in self.db.query(
                "SELECT reason, count(*) AS n FROM feedback WHERE useful = 0 AND created_at >= ? GROUP BY reason",
                (since,),
            )
        }
        return (int(row["n"]), int(row["u"]), reasons) if row else (0, 0, reasons)

    def ui_insights(self, since: str, type: str) -> int:
        return int(
            self.db.scalar(
                "SELECT count(DISTINCT insight_id) FROM ui_events WHERE type = ? AND insight_id IS NOT NULL "
                "AND created_at >= ?",
                (type, since),
            )
            or 0
        )

    def chat_insights(self, since: str) -> int:
        return int(
            self.db.scalar(
                "SELECT count(DISTINCT insight_id) FROM chat_messages WHERE role = 'user' AND created_at >= ?",
                (since,),
            )
            or 0
        )

    def succeeded_runs(self, since: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT created_at, finished_at, cost_rub FROM agent_runs WHERE kind IN ('insight', 'analyze') "
            "AND status = 'succeeded' AND created_at >= ?",
            (since,),
        )
        return [dict(r) for r in rows]

    def run_statuses(self, since: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT kind, status, error_code, count(*) AS n FROM agent_runs WHERE created_at >= ? GROUP BY 1, 2, 3",
            (since,),
        )
        return [dict(r) for r in rows]

    def verification(self, since: str) -> list[tuple[str, dict[str, Any]]]:
        rows = self.db.query("SELECT status, payload_json FROM insights WHERE created_at >= ?", (since,))
        return [(r["status"], json.loads(r["payload_json"]).get("verification", {})) for r in rows]

    def review_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT id, company_id, event_id, headline, status, confidence_level, created_at, review_note, payload_json "
            "FROM insights WHERE status = 'needs_review' OR (status = 'published' AND confidence_level = 'low' "
            "AND reviewed_at IS NULL) ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        out = []
        for r in rows:
            d = dict(r)
            ver = json.loads(d.pop("payload_json")).get("verification", {})
            d["supported_share"] = ver.get("supported_share")
            d["removed_claims"] = ver.get("removed_claims", 0)
            out.append(d)
        return out
