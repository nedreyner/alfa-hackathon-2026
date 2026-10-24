"""Метрики качества и бюджета для /api/quality (docs/12-quality.md §6)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from alfa_insight.appctx import AppContext
from alfa_insight.store.llm import LLMStore
from alfa_insight.store.quality import QualityStore
from alfa_insight.timeutil import parse_dt, to_iso, utc_now

WINDOW_DAYS = 7


class OnlineMetrics(BaseModel):
    feedback_total: int
    useful_rate: float | None
    negative_reasons: dict[str, int]
    source_ctr: float | None
    trace_open_rate: float | None
    followup_rate: float | None
    time_to_insight_ms: dict[str, int | None]
    cost_per_insight_rub: float | None
    run_failure_rate: dict[str, float]
    top_errors: dict[str, int]


class BudgetStats(BaseModel):
    today_spent_rub: float
    daily_limit_rub: float
    mode: str
    by_day: list[dict[str, Any]]
    by_model: list[dict[str, Any]]


class VerificationStats(BaseModel):
    insights: int
    avg_supported_share: float | None
    needs_review_share: float | None
    avg_removed_claims: float | None


class QualityResponse(BaseModel):
    offline: dict[str, Any] | None
    online: OnlineMetrics
    budget: BudgetStats
    verification: VerificationStats
    review_queue_size: int
    window_days: int


def _pct(values: list[int], q: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, round(q * (len(s) - 1)))]


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def quality(app: AppContext, window_days: int = WINDOW_DAYS) -> QualityResponse:
    store = QualityStore(app.db)
    since = to_iso(utc_now() - timedelta(days=window_days))
    total, useful, reasons = store.feedback(since)
    opened = store.ui_insights(since, "insight_open")
    runs = store.succeeded_runs(since)
    durations = [
        int((parse_dt(r["finished_at"]) - parse_dt(r["created_at"])).total_seconds() * 1000)
        for r in runs
        if r["finished_at"]
    ]
    by_kind: dict[str, list[int]] = {}
    errors: dict[str, int] = {}
    for r in store.run_statuses(since):
        n_all, n_fail = by_kind.setdefault(r["kind"], [0, 0])
        by_kind[r["kind"]] = [n_all + r["n"], n_fail + (r["n"] if r["status"] == "failed" else 0)]
        if r["status"] == "failed" and r["error_code"]:
            errors[r["error_code"]] = errors.get(r["error_code"], 0) + r["n"]
    online = OnlineMetrics(
        feedback_total=total, useful_rate=_ratio(useful, total), negative_reasons=reasons,
        source_ctr=_ratio(store.ui_insights(since, "source_open"), opened),
        trace_open_rate=_ratio(store.ui_insights(since, "trace_open"), opened),
        followup_rate=_ratio(store.chat_insights(since), opened),
        time_to_insight_ms={"p50": _pct(durations, 0.5), "p95": _pct(durations, 0.95)},
        cost_per_insight_rub=round(sum(r["cost_rub"] for r in runs) / len(runs), 4) if runs else None,
        run_failure_rate={k: round(f / a, 4) for k, (a, f) in by_kind.items() if a},
        top_errors=dict(sorted(errors.items(), key=lambda kv: -kv[1])[:5]),
    )  # fmt: skip
    budget = app.router.budget
    llm = LLMStore(app.db)
    days = llm.spend_by((utc_now() - timedelta(days=window_days)).date().isoformat())
    by_day: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    for r in days:
        d = by_day.setdefault(r["budget_day"], {"day": r["budget_day"], "cost_rub": 0.0, "by_task": {}})
        d["cost_rub"] = round(d["cost_rub"] + (r["cost_rub"] or 0), 4)
        d["by_task"][r["task"]] = round(d["by_task"].get(r["task"], 0) + (r["cost_rub"] or 0), 4)
        m = by_model.setdefault(
            r["model"],
            {"model": r["model"], "calls": 0, "cached": 0, "tokens_in": 0, "tokens_out": 0, "cost_rub": 0.0},
        )
        for k in ("calls", "cached", "tokens_in", "tokens_out"):
            m[k] += int(r[k] or 0)
        m["cost_rub"] = round(m["cost_rub"] + (r["cost_rub"] or 0), 4)
    for m in by_model.values():
        m["cache_share"] = round(m["cached"] / m["calls"], 4) if m["calls"] else 0.0
    budget_stats = BudgetStats(
        today_spent_rub=round(budget.spent(), 4) if budget else 0.0, daily_limit_rub=app.settings.llm_daily_budget_rub,
        mode=budget.mode() if budget else "normal", by_day=list(by_day.values()),
        by_model=sorted(by_model.values(), key=lambda m: -m["cost_rub"]),
    )  # fmt: skip
    ver = store.verification(since)
    shares: list[float] = [
        float(v["supported_share"]) for _, v in ver if v.get("supported_share") is not None
    ]
    verification = VerificationStats(
        insights=len(ver), avg_supported_share=round(sum(shares) / len(shares), 4) if shares else None,
        needs_review_share=_ratio(sum(1 for s, _ in ver if s == "needs_review"), len(ver)),
        avg_removed_claims=round(sum(v.get("removed_claims", 0) for _, v in ver) / len(ver), 3) if ver else None,
    )  # fmt: skip
    report = app.settings.repo_root / "eval" / "reports" / "latest.json"
    offline = json.loads(report.read_text(encoding="utf-8")) if report.exists() else None
    return QualityResponse(
        offline=offline, online=online, budget=budget_stats, verification=verification,
        review_queue_size=len(store.review_queue()), window_days=window_days,
    )  # fmt: skip
