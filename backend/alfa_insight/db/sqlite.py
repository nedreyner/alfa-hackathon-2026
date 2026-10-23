"""SQLite в режиме WAL: подключение, транзакции, миграции. SQL к SQLite пишется только в `store/`."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from typing import Any

from alfa_insight.timeutil import to_iso, utc_now

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)

Params = Sequence[Any] | dict[str, Any]


class SqliteDB:
    """Одно подключение на процесс; запись сериализуется блокировкой, чтение — свободное."""

    def __init__(self, path: Path | str):
        self.path = Path(path) if str(path) != ":memory:" else path
        self._conn: sqlite3.Connection | None = None
        self._write_lock = threading.RLock()
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            if isinstance(self.path, Path):
                self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            for pragma in PRAGMAS:
                conn.execute(pragma)
            self._conn = conn
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self.connect()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _in_tx(self) -> bool:
        return bool(getattr(self._local, "depth", 0))

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Короткая транзакция на запись. Вложенные вызовы присоединяются к внешней."""
        with self._write_lock:
            depth = getattr(self._local, "depth", 0)
            conn = self.conn
            if depth == 0:
                conn.execute("BEGIN IMMEDIATE")
            self._local.depth = depth + 1
            try:
                yield conn
            except BaseException:
                self._local.depth = depth
                if depth == 0:
                    conn.execute("ROLLBACK")
                raise
            else:
                self._local.depth = depth
                if depth == 0:
                    conn.execute("COMMIT")

    def query(self, sql: str, params: Params = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Params = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Params = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return None if row is None else row[0]

    def execute(self, sql: str, params: Params = ()) -> sqlite3.Cursor:
        if self._in_tx():
            return self.conn.execute(sql, params)
        with self.tx() as conn:
            return conn.execute(sql, params)

    def executemany(self, sql: str, rows: Sequence[Params]) -> sqlite3.Cursor:
        if self._in_tx():
            return self.conn.executemany(sql, rows)
        with self.tx() as conn:
            return conn.executemany(sql, rows)

    # ── миграции ──
    def migrate(self) -> list[str]:
        """Применяет по порядку `migrations/*.sql`, которых нет в `schema_migrations`."""
        conn = self.conn
        with self._write_lock:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
            )
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
            done: list[str] = []
            for version, name, sql in _migration_files():
                if version in applied:
                    continue
                script = (
                    "BEGIN;\n"
                    + sql
                    + "\nINSERT INTO schema_migrations(version, name, applied_at) VALUES "
                    + f"({version}, '{name}', '{to_iso(utc_now())}');\nCOMMIT;"
                )
                try:
                    conn.executescript(script)
                except sqlite3.Error:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
                done.append(name)
            return done


def _migration_files() -> list[tuple[int, str, str]]:
    files = []
    for entry in resources.files("alfa_insight.db").joinpath("migrations").iterdir():
        if entry.name.endswith(".sql"):
            version = int(entry.name.split("_", 1)[0])
            files.append((version, entry.name.removesuffix(".sql"), entry.read_text(encoding="utf-8")))
    return sorted(files)


def open_db(path: Path | str, *, migrate: bool = True) -> SqliteDB:
    db = SqliteDB(path)
    db.connect()
    if migrate:
        db.migrate()
    return db
