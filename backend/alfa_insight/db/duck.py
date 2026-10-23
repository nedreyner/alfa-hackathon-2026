"""Подключения к DuckDB. Файл собирается только `alfa data build`; дальше — только чтение (ADR-14)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb


def connect_rw(path: Path | str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path))


class DuckReader:
    """Соединение только на чтение; курсор на поток, потому что соединение DuckDB не потокобезопасно."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._local = threading.local()
        self._lock = threading.Lock()

    def _base(self) -> duckdb.DuckDBPyConnection:
        with self._lock:
            if self._conn is None:
                if not self.path.exists():
                    raise FileNotFoundError(f"{self.path}: нет файла DuckDB, выполните `alfa data build`")
                self._conn = duckdb.connect(str(self.path), read_only=True)
            return self._conn

    def cursor(self) -> duckdb.DuckDBPyConnection:
        cur = getattr(self._local, "cursor", None)
        if cur is None:
            cur = self._base().cursor()
            self._local.cursor = cur
        return cur

    def rows(self, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
        cur = self.cursor().execute(sql, params or [])
        cols = [d[0] for d in cur.description or []]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def scalar(self, sql: str, params: list[Any] | None = None) -> Any:
        row = self.cursor().execute(sql, params or []).fetchone()
        return None if row is None else row[0]

    def has_table(self, name: str) -> bool:
        return bool(
            self.scalar("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name])
        )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
