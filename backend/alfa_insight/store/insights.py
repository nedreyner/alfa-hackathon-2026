"""Таблицы `insights`, `sources`, `insight_sources` (docs/08-agent.md §8.2, §10)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now

PRIVATE_SOURCE_KINDS = frozenset({"client_data", "user_input"})
EXCERPT_CHARS = 500


class SourceIn(BaseModel):
    id: str
    kind: str
    title: str
    company_id: str | None = None
    publisher: str | None = None
    url: str | None = None
    published_at: str | None = None
    excerpt: str
    payload: dict[str, Any] = {}


class SourceRow(SourceIn):
    created_at: str


class InsightRow(BaseModel):
    id: str
    company_id: str
    event_id: int
    run_id: str
    prompt_version: str
    profile_version: str
    status: str
    headline: str
    direction: str
    impact_level: str
    confidence: float
    confidence_level: str
    payload: dict[str, Any]
    verification: dict[str, Any]
    model: str
    cost_rub: float
    created_at: str
    reviewed_at: str | None
    review_note: str | None


def _insight(row: Any) -> InsightRow:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json"))
    d["verification"] = json.loads(d.pop("verification_json"))
    return InsightRow(**d)


def _source(row: Any) -> SourceRow:
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    return SourceRow(**d)


class InsightStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    # ── источники ──
    def upsert_sources(self, sources: Iterable[SourceIn]) -> None:
        now = to_iso(utc_now())
        rows = []
        for s in sources:
            if s.kind in PRIVATE_SOURCE_KINDS and not s.company_id:
                raise ValueError(f"источник {s.id} вида {s.kind} должен иметь company_id")
            rows.append(
                {
                    **s.model_dump(exclude={"payload", "excerpt"}),
                    "excerpt": s.excerpt[:EXCERPT_CHARS],
                    "payload_json": json.dumps(s.payload, ensure_ascii=False, default=str),
                    "created_at": now,
                }
            )
        self.db.executemany(
            "INSERT INTO sources(id, kind, company_id, title, publisher, url, published_at, excerpt, payload_json, "
            "created_at) VALUES (:id, :kind, :company_id, :title, :publisher, :url, :published_at, :excerpt, "
            ":payload_json, :created_at) ON CONFLICT(id) DO UPDATE SET title = excluded.title, "
            "publisher = excluded.publisher, url = excluded.url, published_at = excluded.published_at, "
            "excerpt = excluded.excerpt, payload_json = excluded.payload_json",
            rows,
        )

    def source(self, source_id: str, *, company_id: str | None = None) -> SourceRow | None:
        """Источник; приватные (client_data, user_input) — только своей компании."""
        row = self.db.query_one("SELECT * FROM sources WHERE id = ?", (source_id,))
        if row is None:
            return None
        src = _source(row)
        if src.company_id is not None and src.company_id != company_id:
            return None
        return src

    def insight_source_ids(self, insight_id: str) -> list[str]:
        rows = self.db.query(
            "SELECT source_id FROM insight_sources WHERE insight_id = ? ORDER BY source_id", (insight_id,)
        )
        return [r["source_id"] for r in rows]

    # ── инсайты ──
    def save(
        self,
        *,
        insight: dict[str, Any],
        verification: dict[str, Any],
        run_id: str,
        event_id: int,
        confidence: float,
        confidence_level: str,
        source_ids: Iterable[str],
    ) -> str:
        """Запись инсайта. Повтор той же пары версий заменяет прежний инсайт (новый id, связи — заново)."""
        ins_id = insight["id"]
        key = (insight["company_id"], event_id, insight["prompt_version"], insight["profile_version"])
        with self.db.tx():
            self.db.execute(
                "DELETE FROM insights WHERE company_id = ? AND event_id = ? AND prompt_version = ? "
                "AND profile_version = ?",
                key,
            )
            self.db.execute(
                "INSERT INTO insights(id, company_id, event_id, run_id, prompt_version, profile_version, status, "
                "headline, direction, impact_level, confidence, confidence_level, payload_json, verification_json, "
                "model, cost_rub, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ins_id,
                    *key[:2],
                    run_id,
                    *key[2:],
                    insight["status"],
                    insight["headline"],
                    insight["direction"],
                    insight["impact_level"],
                    confidence,
                    confidence_level,
                    json.dumps(insight, ensure_ascii=False, default=str),
                    json.dumps(verification, ensure_ascii=False, default=str),
                    insight["model"],
                    insight["cost_rub"],
                    to_iso(utc_now()),
                ),
            )
            self.db.executemany(
                "INSERT OR IGNORE INTO insight_sources(insight_id, source_id) VALUES (?, ?)",
                [(ins_id, sid) for sid in dict.fromkeys(source_ids)],
            )
        return ins_id

    def get(self, insight_id: str) -> InsightRow | None:
        row = self.db.query_one("SELECT * FROM insights WHERE id = ?", (insight_id,))
        return _insight(row) if row else None

    def latest_for(
        self,
        company_id: str,
        event_id: int,
        *,
        prompt_version: str | None = None,
        profile_version: str | None = None,
        statuses: tuple[str, ...] = ("published", "needs_review"),
    ) -> InsightRow | None:
        """Последний инсайт пары; с версиями — только актуальный (иначе `stale` решает вызывающий)."""
        sql = "SELECT * FROM insights WHERE company_id = ? AND event_id = ?"
        params: list[Any] = [company_id, event_id]
        if prompt_version is not None:
            sql += " AND prompt_version = ?"
            params.append(prompt_version)
        if profile_version is not None:
            sql += " AND profile_version = ?"
            params.append(profile_version)
        sql += (
            f" AND status IN ({', '.join('?' for _ in statuses)}) ORDER BY created_at DESC, id DESC LIMIT 1"
        )
        row = self.db.query_one(sql, (*params, *statuses))
        return _insight(row) if row else None

    def latest_by_events(
        self,
        company_id: str,
        event_ids: Iterable[int],
        statuses: tuple[str, ...] = ("published", "needs_review"),
    ) -> dict[int, InsightRow]:
        ids = list(dict.fromkeys(event_ids))
        if not ids:
            return {}
        rows = self.db.query(
            f"SELECT * FROM insights WHERE company_id = ? AND event_id IN ({', '.join('?' for _ in ids)}) "
            f"AND status IN ({', '.join('?' for _ in statuses)}) ORDER BY created_at, id",
            (company_id, *ids, *statuses),
        )
        out: dict[int, InsightRow] = {}
        for r in rows:  # по возрастанию — последний перезаписывает
            out[r["event_id"]] = _insight(r)
        return out

    def by_status(self, status: str, *, limit: int = 50) -> list[InsightRow]:
        rows = self.db.query(
            "SELECT * FROM insights WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, limit)
        )
        return [_insight(r) for r in rows]

    def review(self, insight_id: str, status: str, note: str | None = None) -> InsightRow | None:
        row = self.get(insight_id)
        if row is None:
            return None
        payload = {**row.payload, "status": status}
        self.db.execute(
            "UPDATE insights SET status = ?, reviewed_at = ?, review_note = ?, payload_json = ? WHERE id = ?",
            (
                status,
                to_iso(utc_now()),
                note,
                json.dumps(payload, ensure_ascii=False, default=str),
                insight_id,
            ),
        )
        return self.get(insight_id)

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, count(*) AS n FROM insights GROUP BY status")
        return {r["status"]: r["n"] for r in rows}
