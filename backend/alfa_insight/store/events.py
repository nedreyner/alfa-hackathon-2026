"""События (кластеры новостей): создание, пересчёт агрегатов, сигналы для ранжирования."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal

import orjson
from pydantic import BaseModel, Field

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

KEY_LEMMAS_EVENT = 40
PUBLISHER_BONUS_AT = 3


# ── сигналы события для ранжирования (docs/07-ranking.md §2) ──
class IndustrySignal(BaseModel):
    industry_id: str
    effect: str
    impact: float
    confidence: float


class FactorSignal(BaseModel):
    factor_id: str
    direction: Literal[-1, 1]
    impact: float
    confidence: float


class EventSignal(BaseModel):
    event_id: int
    title: str
    event_type: str
    importance: int
    horizon: str
    first_seen_at: datetime
    last_seen_at: datetime
    publisher_count: int
    max_trust: float
    tag_confidence: float
    geo: list[str] = Field(default_factory=list)
    industries: list[IndustrySignal] = Field(default_factory=list)
    factors: list[FactorSignal] = Field(default_factory=list)
    visibility: Literal["public", "private"] = "public"
    owner_company_id: str | None = None
    injection_suspected: bool = False


class EventRow(BaseModel):
    id: int
    title: str
    summary: str
    event_type: str
    importance: int
    horizon: str
    first_seen_at: str
    last_seen_at: str
    news_count: int
    publisher_count: int
    max_trust: float
    tag_confidence: float
    lead_news_id: int | None
    geo: list[str]
    key_lemmas: list[str]
    visibility: str
    owner_company_id: str | None
    injection_suspected: bool

    @classmethod
    def from_row(cls, row: Any) -> EventRow:
        d = dict(row)
        d["geo"] = orjson.loads(d.pop("geo_json") or "[]")
        d["key_lemmas"] = orjson.loads(d.get("key_lemmas") or "[]")
        d["injection_suspected"] = bool(d.get("injection_suspected"))
        return cls.model_validate({k: v for k, v in d.items() if k in cls.model_fields})


class EventStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def get(self, event_id: int) -> EventRow | None:
        row = self.db.query_one("SELECT * FROM events WHERE id = ?", (event_id,))
        return EventRow.from_row(row) if row else None

    def candidates(
        self, since: str, event_type: str, industry_ids: list[str], factor_ids: list[str]
    ) -> list[tuple[EventRow, set[str], set[str]]]:
        """Публичные события за окно, связанные с новостью типом, отраслью или фактором."""
        rows = self.db.query(
            "SELECT * FROM events WHERE visibility = 'public' AND last_seen_at >= ? ORDER BY last_seen_at DESC",
            (since,),
        )
        out = []
        for r in rows:
            ev = EventRow.from_row(r)
            inds = {
                x["industry_id"]
                for x in self.db.query(
                    "SELECT industry_id FROM event_industries WHERE event_id = ?", (ev.id,)
                )
            }
            facs = {
                x["factor_id"]
                for x in self.db.query("SELECT factor_id FROM event_factors WHERE event_id = ?", (ev.id,))
            }
            if ev.event_type == event_type or inds & set(industry_ids) or facs & set(factor_ids):
                out.append((ev, inds, facs))
        return out

    def entities(self, event_id: int) -> set[str]:
        rows = self.db.query(
            "SELECT DISTINCT lower(e.name) AS name FROM news_entities e JOIN news n ON n.id = e.news_id WHERE n.event_id = ?",
            (event_id,),
        )
        return {r["name"] for r in rows}

    def create(self, news_id: int, *, visibility: str = "public", owner_company_id: str | None = None) -> int:
        now = to_iso(utc_now())
        cur = self.db.execute(
            "INSERT INTO events(title, summary, event_type, importance, horizon, first_seen_at, last_seen_at, "
            "max_trust, visibility, owner_company_id, created_at, updated_at) "
            "SELECT n.title, COALESCE(t.summary, n.title), COALESCE(t.event_type, 'other'), COALESCE(t.importance, 1), "
            "COALESCE(t.horizon, 'weeks'), n.published_at, n.published_at, n.trust, ?, ?, ?, ? "
            "FROM news n LEFT JOIN news_tags t ON t.news_id = n.id WHERE n.id = ?",
            (visibility, owner_company_id, now, now, news_id),
        )
        event_id = int(cur.lastrowid or 0)
        self.attach(news_id, event_id)
        return event_id

    def attach(self, news_id: int, event_id: int) -> None:
        self.db.execute(
            "UPDATE news SET event_id = ?, status = 'clustered' WHERE id = ?", (event_id, news_id)
        )

    def recompute(
        self, event_id: int, key_lemmas_by_news: dict[int, list[str]], title_lemmas: str, summary_lemmas: str
    ) -> None:
        """Пересчитать агрегаты события по всем его новостям (docs/06 §9 п. 5)."""
        members = self.db.query(
            "SELECT n.id, n.publisher, n.trust, n.published_at, n.title, n.injection_flags, "
            "t.summary, t.event_type, t.importance, t.horizon, t.payload_json "
            "FROM news n LEFT JOIN news_tags t ON t.news_id = n.id WHERE n.event_id = ? ORDER BY n.published_at, n.id",
            (event_id,),
        )
        if not members:
            return
        lead = sorted(members, key=lambda m: (-m["trust"], m["published_at"], m["id"]))[0]
        publishers = {m["publisher"] for m in members}
        importance = max(int(m["importance"] or 1) for m in members)
        if len(publishers) >= PUBLISHER_BONUS_AT:
            importance += 1
        injection = any(
            orjson.loads(m["injection_flags"] or "[]")
            or (m["payload_json"] and orjson.loads(m["payload_json"]).get("injection_suspected"))
            for m in members
        )
        ids = [m["id"] for m in members]
        marks = ",".join("?" * len(ids))
        industries: dict[tuple[str, str], tuple[float, float, str | None]] = {}
        for r in self.db.query(f"SELECT * FROM news_industries WHERE news_id IN ({marks})", ids):
            key = (r["industry_id"], r["effect"])
            prev = industries.get(key)
            industries[key] = (
                max(r["impact"], prev[0]) if prev else r["impact"],
                max(r["confidence"], prev[1]) if prev else r["confidence"],
                (prev[2] if prev else None) or r["rationale"],
            )
        factors: dict[
            str, tuple[int, float, float, float, str | None]
        ] = {}  # dir, impact, conf, best_conf, rationale
        for r in self.db.query(f"SELECT * FROM news_factors WHERE news_id IN ({marks})", ids):
            prev_f = factors.get(r["factor_id"])
            if prev_f is None:
                factors[r["factor_id"]] = (
                    r["direction"],
                    r["impact"],
                    r["confidence"],
                    r["confidence"],
                    r["rationale"],
                )
            else:
                direction = r["direction"] if r["confidence"] > prev_f[3] else prev_f[0]
                factors[r["factor_id"]] = (
                    direction,
                    max(prev_f[1], r["impact"]),
                    max(prev_f[2], r["confidence"]),
                    max(prev_f[3], r["confidence"]),
                    prev_f[4] or r["rationale"],
                )
        geo = sorted(
            {
                r["geo"]
                for r in self.db.query(f"SELECT DISTINCT geo FROM news_geo WHERE news_id IN ({marks})", ids)
            }
        )
        confs = [c for (_, c, _) in industries.values()] + [f[2] for f in factors.values()]
        tag_conf = sum(confs) / len(confs) if confs else 0.5
        counter: Counter[str] = Counter()
        for nid in ids:
            counter.update(key_lemmas_by_news.get(nid, []))
        key_lemmas = [w for w, _ in counter.most_common(KEY_LEMMAS_EVENT)]
        now = to_iso(utc_now())
        with self.db.tx():
            self.db.execute(
                "UPDATE events SET title = ?, summary = ?, event_type = ?, importance = ?, horizon = ?, "
                "first_seen_at = ?, last_seen_at = ?, news_count = ?, publisher_count = ?, max_trust = ?, "
                "tag_confidence = ?, lead_news_id = ?, geo_json = ?, key_lemmas = ?, injection_suspected = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    lead["title"],
                    lead["summary"] or lead["title"],
                    lead["event_type"] or "other",
                    min(5, importance),
                    lead["horizon"] or "weeks",
                    members[0]["published_at"],
                    max(m["published_at"] for m in members),
                    len(members),
                    len(publishers),
                    max(m["trust"] for m in members),
                    round(tag_conf, 4),
                    lead["id"],
                    orjson.dumps(geo).decode(),
                    orjson.dumps(key_lemmas, option=orjson.OPT_NON_STR_KEYS).decode(),
                    int(injection),
                    now,
                    event_id,
                ),
            )
            self.db.execute("DELETE FROM event_industries WHERE event_id = ?", (event_id,))
            self.db.executemany(
                "INSERT INTO event_industries(event_id, industry_id, effect, impact, confidence, rationale) VALUES (?, ?, ?, ?, ?, ?)",
                [(event_id, k[0], k[1], v[0], v[1], v[2]) for k, v in industries.items()],
            )
            self.db.execute("DELETE FROM event_factors WHERE event_id = ?", (event_id,))
            self.db.executemany(
                "INSERT INTO event_factors(event_id, factor_id, direction, impact, confidence, rationale) VALUES (?, ?, ?, ?, ?, ?)",
                [(event_id, fid, v[0], v[1], v[2], v[4]) for fid, v in factors.items()],
            )
            self.db.execute("DELETE FROM events_fts WHERE rowid = ?", (event_id,))
            self.db.execute(
                "INSERT INTO events_fts(rowid, title_lemmas, summary_lemmas) VALUES (?, ?, ?)",
                (event_id, title_lemmas, summary_lemmas),
            )

    def news_ids(self, event_id: int) -> list[int]:
        return [
            r["id"]
            for r in self.db.query(
                "SELECT id FROM news WHERE event_id = ? ORDER BY published_at, id", (event_id,)
            )
        ]

    def list_ids(self, *, visibility: str | None = "public", since: str | None = None) -> list[int]:
        sql = "SELECT id FROM events WHERE 1 = 1"
        params: list[Any] = []
        if visibility:
            sql += " AND visibility = ?"
            params.append(visibility)
        if since:
            sql += " AND last_seen_at >= ?"
            params.append(since)
        return [r["id"] for r in self.db.query(sql + " ORDER BY id", params)]

    def load_signals(self, event_ids: list[int]) -> list[EventSignal]:
        if not event_ids:
            return []
        marks = ",".join("?" * len(event_ids))
        events = {r["id"]: r for r in self.db.query(f"SELECT * FROM events WHERE id IN ({marks})", event_ids)}
        inds: dict[int, list[IndustrySignal]] = {i: [] for i in event_ids}
        for r in self.db.query(f"SELECT * FROM event_industries WHERE event_id IN ({marks})", event_ids):
            inds[r["event_id"]].append(
                IndustrySignal(
                    industry_id=r["industry_id"],
                    effect=r["effect"],
                    impact=r["impact"],
                    confidence=r["confidence"],
                )
            )
        facs: dict[int, list[FactorSignal]] = {i: [] for i in event_ids}
        for r in self.db.query(f"SELECT * FROM event_factors WHERE event_id IN ({marks})", event_ids):
            facs[r["event_id"]].append(
                FactorSignal(
                    factor_id=r["factor_id"],
                    direction=r["direction"],
                    impact=r["impact"],
                    confidence=r["confidence"],
                )
            )
        out = []
        for eid in event_ids:
            e = events.get(eid)
            if e is None:
                continue
            out.append(
                EventSignal(
                    event_id=eid,
                    title=e["title"],
                    event_type=e["event_type"],
                    importance=e["importance"],
                    horizon=e["horizon"],
                    first_seen_at=parse_dt(e["first_seen_at"]),
                    last_seen_at=parse_dt(e["last_seen_at"]),
                    publisher_count=e["publisher_count"],
                    max_trust=e["max_trust"],
                    tag_confidence=e["tag_confidence"],
                    geo=orjson.loads(e["geo_json"] or "[]"),
                    industries=sorted(inds[eid], key=lambda x: (-x.impact, x.industry_id)),
                    factors=sorted(facs[eid], key=lambda x: (-x.impact, x.factor_id)),
                    visibility=e["visibility"],
                    owner_company_id=e["owner_company_id"],
                    injection_suspected=bool(e["injection_suspected"]),
                )
            )
        return out
