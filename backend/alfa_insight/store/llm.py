"""Таблицы `llm_cache` и `llm_calls`: кеш ответов и учёт вызовов."""

from __future__ import annotations

from typing import Any

import orjson

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.llm.types import LLMCallRecord
from alfa_insight.timeutil import to_iso, utc_now


class LLMStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    # ── кеш ──
    def cache_get(self, key: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT response_json FROM llm_cache WHERE key = ?", (key,))
        return None if row is None else orjson.loads(row["response_json"])

    def cache_hit(self, key: str) -> None:
        self.db.execute(
            "UPDATE llm_cache SET hits = hits + 1, last_hit_at = ? WHERE key = ?", (to_iso(utc_now()), key)
        )

    def cache_put(
        self,
        key: str,
        *,
        task: str,
        model: str,
        prompt_version: str,
        request: dict[str, Any],
        response: dict[str, Any],
        tokens_in: int,
        tokens_out: int,
        cost_rub: float,
    ) -> None:
        self.db.execute(
            "INSERT INTO llm_cache(key, task, model, prompt_version, request_json, response_json, tokens_in, "
            "tokens_out, cost_rub, hits, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?) "
            "ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json, model = excluded.model, "
            "tokens_in = excluded.tokens_in, tokens_out = excluded.tokens_out, cost_rub = excluded.cost_rub",
            (
                key,
                task,
                model,
                prompt_version,
                orjson.dumps(request).decode(),
                orjson.dumps(response).decode(),
                tokens_in,
                tokens_out,
                cost_rub,
                to_iso(utc_now()),
            ),
        )

    def cache_delete(self, key: str) -> None:
        self.db.execute("DELETE FROM llm_cache WHERE key = ?", (key,))

    def cache_stats(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT task, count(*) AS entries, sum(hits) AS hits, sum(cost_rub) AS cost_rub "
            "FROM llm_cache GROUP BY task ORDER BY task"
        )
        return [dict(r) for r in rows]

    def cache_clear(self, task: str | None = None) -> int:
        if task:
            return self.db.execute("DELETE FROM llm_cache WHERE task = ?", (task,)).rowcount
        return self.db.execute("DELETE FROM llm_cache").rowcount

    def cache_export(self, keys: list[str] | None = None) -> list[dict[str, Any]]:
        if keys is None:
            rows = self.db.query("SELECT * FROM llm_cache ORDER BY created_at, key")
        else:
            if not keys:
                return []
            marks = ",".join("?" * len(keys))
            rows = self.db.query(
                f"SELECT * FROM llm_cache WHERE key IN ({marks}) ORDER BY created_at, key", keys
            )
        out = []
        for r in rows:
            item = dict(r)
            item["request"] = orjson.loads(item.pop("request_json"))
            item["response"] = orjson.loads(item.pop("response_json"))
            item.pop("hits", None)
            item.pop("last_hit_at", None)
            out.append(item)
        return out

    def cache_import(self, items: list[dict[str, Any]]) -> int:
        n = 0
        with self.db.tx():
            for it in items:
                cur = self.db.execute(
                    "INSERT OR IGNORE INTO llm_cache(key, task, model, prompt_version, request_json, response_json, "
                    "tokens_in, tokens_out, cost_rub, hits, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                    (
                        it["key"],
                        it["task"],
                        it["model"],
                        it["prompt_version"],
                        orjson.dumps(it["request"]).decode(),
                        orjson.dumps(it["response"]).decode(),
                        it.get("tokens_in", 0),
                        it.get("tokens_out", 0),
                        it.get("cost_rub", 0.0),
                        it.get("created_at") or to_iso(utc_now()),
                    ),
                )
                n += cur.rowcount
        return n

    # ── учёт вызовов ──
    def record_call(self, rec: LLMCallRecord) -> None:
        self.db.execute(
            "INSERT INTO llm_calls(ts, budget_day, task, model, priority, run_id, cached, status, tokens_in, "
            "tokens_out, cost_rub, latency_ms, base_url_kind, error, cache_key) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec.ts,
                rec.budget_day,
                rec.task,
                rec.model,
                rec.priority,
                rec.run_id,
                int(rec.cached),
                rec.status,
                rec.tokens_in,
                rec.tokens_out,
                rec.cost_rub,
                rec.latency_ms,
                rec.base_url_kind,
                rec.error,
                rec.cache_key,
            ),
        )

    def spent(self, budget_day: str) -> float:
        value = self.db.scalar(
            "SELECT COALESCE(SUM(cost_rub), 0) FROM llm_calls WHERE budget_day = ? AND cached = 0",
            (budget_day,),
        )
        return float(value or 0.0)

    def run_cost(self, run_id: str) -> float:
        value = self.db.scalar(
            "SELECT COALESCE(SUM(cost_rub), 0) FROM llm_calls WHERE run_id = ? AND cached = 0", (run_id,)
        )
        return float(value or 0.0)

    def run_cache_keys(self, run_ids: list[str]) -> list[str]:
        """Ключи кеша, записанные в прогонах (для `llm cache export --runs`)."""
        if not run_ids:
            return []
        marks = ",".join("?" * len(run_ids))
        rows = self.db.query(
            f"SELECT DISTINCT cache_key FROM llm_calls WHERE run_id IN ({marks}) AND cache_key IS NOT NULL",
            run_ids,
        )
        return [r["cache_key"] for r in rows]

    def spend_by(self, since_day: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT budget_day, task, model, count(*) AS calls, sum(cached) AS cached, "
            "sum(tokens_in) AS tokens_in, sum(tokens_out) AS tokens_out, round(sum(cost_rub), 4) AS cost_rub "
            "FROM llm_calls WHERE budget_day >= ? GROUP BY 1, 2, 3 ORDER BY 1 DESC, cost_rub DESC",
            (since_day,),
        )
        return [dict(r) for r in rows]
