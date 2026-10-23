from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.store.kv import KVStore

EXPECTED_TABLES = {
    "kv",
    "events",
    "event_industries",
    "event_factors",
    "news",
    "news_tags",
    "news_industries",
    "news_factors",
    "news_geo",
    "news_entities",
    "research_docs",
    "research_chunks",
    "research_items",
    "macro_series",
    "rankings",
    "agent_runs",
    "trace_events",
    "insights",
    "sources",
    "insight_sources",
    "chat_messages",
    "feedback",
    "ui_events",
    "profile_overrides",
    "leads",
    "llm_cache",
    "llm_calls",
}
FTS_TABLES = {"events_fts", "news_fts", "research_fts"}


def test_fts5_available() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    conn.execute("INSERT INTO t(body) VALUES ('пошлина металлопрокат')")
    assert conn.execute("SELECT count(*) FROM t WHERE t MATCH 'пошлина'").fetchone()[0] == 1


def test_migrate_twice_creates_all_tables(tmp_path: Path) -> None:
    db = SqliteDB(tmp_path / "app.sqlite")
    assert db.migrate() == ["0001_init", "0002_llm_calls_cache_key"]
    assert db.migrate() == []
    names = {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert names >= EXPECTED_TABLES | FTS_TABLES
    assert db.scalar("PRAGMA journal_mode") == "wal"
    assert db.scalar("PRAGMA foreign_keys") == 1


def test_tx_rollback_and_nesting(tmp_path: Path) -> None:
    db = SqliteDB(tmp_path / "app.sqlite")
    db.migrate()
    kv = KVStore(db)
    with pytest.raises(RuntimeError), db.tx():
        kv.set("a", 1)
        raise RuntimeError("boom")
    assert kv.get("a") is None
    with db.tx():
        kv.set("a", {"x": [1, 2]})
        with db.tx():
            kv.set("b", "текст")
    assert kv.get("a") == {"x": [1, 2]}
    assert kv.prefix("") == {"a": {"x": [1, 2]}, "b": "текст"}
    kv.delete("a")
    assert kv.get("a", "default") == "default"
