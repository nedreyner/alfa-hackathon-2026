"""Служебное хранилище «ключ → JSON»: водяные знаки, статусы источников."""

from __future__ import annotations

from typing import Any

import orjson

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.timeutil import to_iso, utc_now


class KVStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        raw = self.db.scalar("SELECT value_json FROM kv WHERE key = ?", (key,))
        return default if raw is None else orjson.loads(raw)

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO kv(key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, orjson.dumps(value).decode(), to_iso(utc_now())),
        )

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM kv WHERE key = ?", (key,))

    def prefix(self, prefix: str) -> dict[str, Any]:
        rows = self.db.query("SELECT key, value_json FROM kv WHERE key LIKE ? || '%'", (prefix,))
        return {row["key"]: orjson.loads(row["value_json"]) for row in rows}
