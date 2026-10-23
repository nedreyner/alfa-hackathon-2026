"""Время: хранение в UTC (ISO 8601 с `Z`), Москва — только для отображения и суточной границы бюджета."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    return ensure_utc(dt).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return ensure_utc(datetime.fromisoformat(text))


def budget_day(dt: datetime | None = None, tz: str = "Europe/Moscow") -> date:
    return ensure_utc(dt or utc_now()).astimezone(ZoneInfo(tz)).date()


def msk(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(MSK)
