"""Правки профиля компании пользователем (`profile_overrides`)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

import orjson
from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

OverrideField = Literal["industry_id", "ved", "products", "notes"]


class Override(BaseModel):
    field: OverrideField
    value: Any
    session_id: str
    updated_at: datetime


class ProfileOverridesRepo:
    def __init__(self, db: SqliteDB):
        self.db = db

    def list(self, company_id: str) -> list[Override]:
        rows = self.db.query(
            "SELECT field, value_json, session_id, updated_at FROM profile_overrides WHERE company_id = ? ORDER BY field",
            (company_id,),
        )
        return [
            Override(
                field=r["field"],
                value=orjson.loads(r["value_json"]),
                session_id=r["session_id"],
                updated_at=parse_dt(r["updated_at"]),
            )
            for r in rows
        ]

    def upsert(self, company_id: str, field: OverrideField, value: Any, session_id: str) -> None:
        self.db.execute(
            "INSERT INTO profile_overrides(company_id, field, value_json, session_id, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(company_id, field) DO UPDATE SET value_json = excluded.value_json, "
            "session_id = excluded.session_id, updated_at = excluded.updated_at",
            (company_id, field, orjson.dumps(value).decode(), session_id, to_iso(utc_now())),
        )

    def delete(self, company_id: str, field: OverrideField) -> None:
        self.db.execute(
            "DELETE FROM profile_overrides WHERE company_id = ? AND field = ?", (company_id, field)
        )
