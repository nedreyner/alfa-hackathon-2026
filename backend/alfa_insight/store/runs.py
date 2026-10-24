"""Таблицы `agent_runs` и `trace_events`: прогоны агента и их трасса (docs/08-agent.md §2, §11)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.ids import new_id
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

FINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_STATUSES = ("queued", "running")
PRIORITY_ORDER = {"interactive": 0, "precompute": 1, "background": 2}


class RunRow(BaseModel):
    id: str
    kind: str
    mode: str
    status: str
    priority: str
    company_id: str
    role: str | None
    event_id: int | None
    insight_id: str | None
    session_id: str | None
    input: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    tokens_in: int
    tokens_out: int
    cost_rub: float
    created_at: str
    started_at: str | None
    finished_at: str | None

    @property
    def final(self) -> bool:
        return self.status in FINAL_STATUSES

    @property
    def duration_ms(self) -> int | None:
        if not self.started_at or not self.finished_at:
            return None
        return int((parse_dt(self.finished_at) - parse_dt(self.started_at)).total_seconds() * 1000)


class TraceRow(BaseModel):
    seq: int
    ts: str
    type: str
    phase: str
    title: str
    status: str
    payload: dict[str, Any]
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_rub: float | None
    latency_ms: int | None


def _run(row: Any) -> RunRow:
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json") or "{}")
    raw = d.pop("result_json")
    d["result"] = json.loads(raw) if raw else None
    return RunRow(**d)


class RunStore:
    def __init__(self, db: SqliteDB):
        self.db = db

    # ── прогоны ──
    def create(
        self,
        *,
        kind: str,
        mode: str,
        company_id: str,
        priority: str = "interactive",
        role: str | None = None,
        event_id: int | None = None,
        session_id: str | None = None,
        input: dict[str, Any] | None = None,
        status: str = "queued",
    ) -> str:
        run_id = new_id("run")
        self.db.execute(
            "INSERT INTO agent_runs(id, kind, mode, status, priority, company_id, role, event_id, session_id, "
            "input_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                kind,
                mode,
                status,
                priority,
                company_id,
                role,
                event_id,
                session_id,
                json.dumps(input or {}, ensure_ascii=False),
                to_iso(utc_now()),
            ),
        )
        return run_id

    def get(self, run_id: str) -> RunRow | None:
        row = self.db.query_one("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        return _run(row) if row else None

    def start(self, run_id: str) -> bool:
        """queued → running; False, если прогон уже взят другим исполнителем."""
        cur = self.db.execute(
            "UPDATE agent_runs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
            (to_iso(utc_now()), run_id),
        )
        return cur.rowcount == 1

    def claim_next(self, priorities: tuple[str, ...] | None = None) -> RunRow | None:
        """Взять самый приоритетный queued-прогон (interactive → precompute → background, FIFO)."""
        allowed = priorities or tuple(PRIORITY_ORDER)
        marks = ", ".join("?" for _ in allowed)
        with self.db.tx():
            row = self.db.query_one(
                f"SELECT id FROM agent_runs WHERE status = 'queued' AND priority IN ({marks}) "
                "ORDER BY CASE priority WHEN 'interactive' THEN 0 WHEN 'precompute' THEN 1 ELSE 2 END, "
                "created_at, id LIMIT 1",
                allowed,
            )
            if row is None or not self.start(row["id"]):
                return None
        return self.get(row["id"])

    def add_usage(self, run_id: str, *, tokens_in: int, tokens_out: int, cost_rub: float) -> None:
        self.db.execute(
            "UPDATE agent_runs SET tokens_in = tokens_in + ?, tokens_out = tokens_out + ?, "
            "cost_rub = cost_rub + ? WHERE id = ?",
            (tokens_in, tokens_out, cost_rub, run_id),
        )

    def succeed(
        self, run_id: str, *, insight_id: str | None = None, result: dict[str, Any] | None = None
    ) -> None:
        self.db.execute(
            "UPDATE agent_runs SET status = 'succeeded', insight_id = COALESCE(?, insight_id), "
            "result_json = ?, finished_at = ? WHERE id = ?",
            (
                insight_id,
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                to_iso(utc_now()),
                run_id,
            ),
        )

    def fail(self, run_id: str, code: str, message: str, *, status: str = "failed") -> None:
        self.db.execute(
            "UPDATE agent_runs SET status = ?, error_code = ?, error_message = ?, finished_at = ?, "
            "started_at = COALESCE(started_at, ?) WHERE id = ? AND status IN ('queued', 'running')",
            (status, code, message, to_iso(utc_now()), to_iso(utc_now()), run_id),
        )

    def set_event(self, run_id: str, event_id: int) -> None:
        """intake фичи B создаёт приватное событие уже во время прогона."""
        self.db.execute("UPDATE agent_runs SET event_id = ? WHERE id = ?", (event_id, run_id))

    def active_for(self, company_id: str, event_id: int, kind: str = "insight") -> RunRow | None:
        row = self.db.query_one(
            "SELECT * FROM agent_runs WHERE company_id = ? AND event_id = ? AND kind = ? "
            "AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
            (company_id, event_id, kind),
        )
        return _run(row) if row else None

    def list_for_company(self, company_id: str, kind: str, *, limit: int = 20) -> list[RunRow]:
        rows = self.db.query(
            "SELECT * FROM agent_runs WHERE company_id = ? AND kind = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (company_id, kind, limit),
        )
        return [_run(r) for r in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, count(*) AS n FROM agent_runs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def recover_stale(self) -> int:
        """После перезапуска процесса: running → failed(interrupted). queued остаются в очереди."""
        ids = [r["id"] for r in self.db.query("SELECT id FROM agent_runs WHERE status = 'running'")]
        for run_id in ids:
            self.fail(run_id, "interrupted", "Разбор прерван, запустите заново")
            seq = self.last_seq(run_id) + 1
            self.add_trace(
                run_id,
                seq,
                type="run.failed",
                phase="finalize",
                title="Разбор прерван перезапуском сервиса",
                status="error",
                payload={"error_code": "interrupted"},
            )
        return len(ids)

    # ── трасса ──
    def last_seq(self, run_id: str) -> int:
        return int(
            self.db.scalar("SELECT COALESCE(max(seq), 0) FROM trace_events WHERE run_id = ?", (run_id,))
        )

    def add_trace(
        self,
        run_id: str,
        seq: int,
        *,
        type: str,
        phase: str,
        title: str,
        status: str = "ok",
        payload: dict[str, Any] | None = None,
        model: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        cost_rub: float | None = None,
        latency_ms: int | None = None,
    ) -> None:
        self.db.execute(
            "INSERT INTO trace_events(run_id, seq, ts, type, phase, title, status, payload_json, model, "
            "tokens_in, tokens_out, cost_rub, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                to_iso(utc_now()),
                type,
                phase,
                title,
                status,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                model,
                tokens_in,
                tokens_out,
                cost_rub,
                latency_ms,
            ),
        )

    def trace(self, run_id: str, *, after_seq: int = 0, limit: int = 1000) -> list[TraceRow]:
        rows = self.db.query(
            "SELECT * FROM trace_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (run_id, after_seq, limit),
        )
        out = []
        for r in rows:
            d = dict(r)
            d.pop("run_id")
            d["payload"] = json.loads(d.pop("payload_json") or "{}")
            out.append(TraceRow(**d))
        return out
