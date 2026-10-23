"""Макроряды ЦБ (`macro_series`) и сводки для агента и интерфейса (docs/06-ingestion-search.md §12)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now

NAMES = {
    "key_rate": ("Ключевая ставка ЦБ", "%"),
    "fx_usd": ("Курс доллара", "₽"),
    "fx_eur": ("Курс евро", "₽"),
    "fx_cny": ("Курс юаня", "₽"),
    "fx_try": ("Курс лиры", "₽"),
    "fx_aed": ("Курс дирхама", "₽"),
    "fx_inr": ("Курс рупии", "₽"),
    "fx_kzt": ("Курс тенге", "₽"),
}


class MacroPoint(BaseModel):
    date: date
    value: float


class MacroSummary(BaseModel):
    indicator: str
    name: str
    unit: Literal["%", "₽"]
    latest: MacroPoint
    change_7d: float | None
    change_30d: float | None
    min_90d: float
    max_90d: float
    series: list[MacroPoint]
    source: Literal["cbr", "snapshot"]


class MacroStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def upsert(self, indicator: str, points: list[tuple[str, float]], source: str = "cbr") -> int:
        now = to_iso(utc_now())
        self.db.executemany(
            "INSERT OR REPLACE INTO macro_series(indicator, date, value, source, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [(indicator, d, v, source, now) for d, v in points],
        )
        return len(points)

    def last_date(self, indicator: str) -> date | None:
        value = self.db.scalar("SELECT max(date) FROM macro_series WHERE indicator = ?", (indicator,))
        return date.fromisoformat(value) if value else None

    def count(self) -> int:
        return int(self.db.scalar("SELECT count(*) FROM macro_series") or 0)

    def series(self, indicator: str, since: date | None = None) -> list[tuple[date, float, str]]:
        sql = "SELECT date, value, source FROM macro_series WHERE indicator = ?"
        params: list[object] = [indicator]
        if since:
            sql += " AND date >= ?"
            params.append(since.isoformat())
        return [
            (date.fromisoformat(r["date"]), r["value"], r["source"])
            for r in self.db.query(sql + " ORDER BY date", params)
        ]

    def indicators(self) -> list[str]:
        return [
            r["indicator"]
            for r in self.db.query("SELECT DISTINCT indicator FROM macro_series ORDER BY indicator")
        ]

    def summary(self, indicator: str, *, days: int = 90, weekly: bool = False) -> MacroSummary | None:
        all_points = self.series(indicator)
        if not all_points:
            return None
        latest_d, latest_v, source = all_points[-1]
        window = [(d, v) for d, v, _ in all_points if d >= latest_d - timedelta(days=days)]

        def value_at(target: date) -> float | None:
            prior = [v for d, v, _ in all_points if d <= target]
            return prior[-1] if prior else None

        def change(n: int) -> float | None:
            past = value_at(latest_d - timedelta(days=n))
            return None if past is None else round(latest_v - past, 6)

        pts = window
        if weekly:
            pts = [p for i, p in enumerate(window) if i % 7 == 0 or i == len(window) - 1]
        name, unit = NAMES.get(indicator, (indicator, "₽"))
        return MacroSummary(
            indicator=indicator,
            name=name,
            unit=unit,  # type: ignore[arg-type]
            latest=MacroPoint(date=latest_d, value=latest_v),
            change_7d=change(7),
            change_30d=change(30),
            min_90d=min(v for _, v in window),
            max_90d=max(v for _, v in window),
            series=[MacroPoint(date=d, value=v) for d, v in pts],
            source=source,  # type: ignore[arg-type]
        )
