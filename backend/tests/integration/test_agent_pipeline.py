from __future__ import annotations

import asyncio

import pytest

from alfa_insight.agent.schemas import Insight
from alfa_insight.errors import BudgetExceeded
from alfa_insight.ingest.macro import load_snapshot
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.runs import RunStore

COMPANY = "SYN-DEMO-02"


def metal_event(app) -> int:  # type: ignore[no-untyped-def]
    """Событие, где главный путь влияния для девелопера — поставщики-металлурги, и путей ≥ 3."""
    events = EventStore(app.db)
    profile = app.profiles.get(COMPANY)
    best = None
    for sig in events.load_signals(events.list_ids()):
        paths = app.ranking.rank_one(sig, profile, "cfo").exposure.paths
        metal = [p for p in paths if p.channel == "supply" and p.industry_id == "metallurgy"]
        if len(paths) >= 3 and metal and (best is None or metal[0].contribution > best[0]):
            best = (metal[0].contribution, sig.event_id)
    assert best is not None, "в seed нет металлургического события с тремя путями"
    return best[1]


async def _start(runner: JobRunner, event_id: int):  # type: ignore[no-untyped-def]
    res = runner.start_interactive(COMPANY, "cfo", event_id, session_id="s1")
    await runner.wait_all()
    return res


def test_insight_end_to_end(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    load_snapshot(MacroStore(app.db), app.settings.seed_dir / "macro.json")
    event_id = metal_event(app)
    runner = JobRunner(app)
    started = asyncio.run(_start(runner, event_id))
    assert started.status == "started" and started.run_id
    run = RunStore(app.db).get(started.run_id)
    assert run is not None and run.status == "succeeded", (run.error_code, run.error_message) if run else None
    row = InsightStore(app.db).get(run.insight_id)  # type: ignore[arg-type]
    assert row is not None
    ins = Insight.model_validate(row.payload)
    assert ins.what_happened.facts and ins.consequences and ins.actions and ins.why_it_matters.summary
    assert ins.status in ("published", "needs_review") and ins.trace_id == run.id
    assert ins.sources and all(":" in s.id for s in ins.sources)
    refs = {r for _, c in ins.claims() for r in c.refs}
    assert refs and refs <= {s.id for s in ins.sources} and not any(r.startswith("E") for r in refs)
    assert len([n for n in ins.chain.nodes if n.kind == "consequence"]) == 3 and len(ins.chain.edges) == 9
    assert any(n.source_ids for n in ins.chain.nodes if n.kind == "exposure")
    assert 0 < ins.confidence.value <= 1 and ins.confidence.reasons
    assert ins.verification.attempts >= 1 and ins.event.id == event_id and ins.event.publishers
    assert (
        ins.prompt_version == "draft_v1+verify_v1"
        and ins.profile_version == app.profiles.get(COMPANY).profile_version
    )
    private = [s for s in ins.sources if s.kind == "client_data"]
    assert private and InsightStore(app.db).source(private[0].id, company_id="SYN-DEMO-01") is None

    trace = RunStore(app.db).trace(run.id)
    types = [t.type for t in trace]
    phases = {t.phase for t in trace}
    assert types[0] == "run.started" and types[-1] == "run.completed"
    assert {"plan", "tools", "draft", "verify", "finalize"} <= phases
    assert {
        "plan",
        "tool.call",
        "tool.result",
        "evidence.added",
        "llm.call",
        "draft.ready",
        "verify.report",
    } <= set(types)
    assert [t.seq for t in trace] == list(range(1, len(trace) + 1))
    llm_tasks = [t.payload["task"] for t in trace if t.type == "llm.call"]
    assert llm_tasks[:2] == ["draft", "verify"]

    # повторный запрос — готовый инсайт, без второго прогона
    again = asyncio.run(_start(runner, event_id))
    assert again.status == "ready" and again.insight_id == ins.id
    assert len(RunStore(app.db).list_for_company(COMPANY, "insight")) == 1


def test_timeout_budget_and_recovery(seeded_ctx, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    event_id = metal_event(app)
    runner = JobRunner(app)
    runs = RunStore(app.db)

    async def slow(ctx, **kw):  # type: ignore[no-untyped-def]
        await asyncio.sleep(5)

    monkeypatch.setattr("alfa_insight.services.jobs.run_agent", slow)
    monkeypatch.setattr(app.settings, "agent_run_timeout_s", 0.2)
    res = asyncio.run(_start(runner, event_id))
    run = runs.get(res.run_id)  # type: ignore[arg-type]
    assert run is not None and (run.status, run.error_code) == ("failed", "timeout")
    assert runs.trace(run.id)[-1].type == "run.failed"

    async def broke(ctx, **kw):  # type: ignore[no-untyped-def]
        raise BudgetExceeded("day")

    monkeypatch.setattr("alfa_insight.services.jobs.run_agent", broke)
    rid = runs.create(
        kind="insight",
        mode="pipeline",
        company_id=COMPANY,
        role="cfo",
        event_id=event_id,
        priority="precompute",
    )
    runs.create(
        kind="insight",
        mode="pipeline",
        company_id=COMPANY,
        role="cfo",
        event_id=event_id,
        priority="precompute",
    )
    done = asyncio.run(runner.process_queue(concurrency=1))
    assert done == 1  # очередь остановилась на дневном бюджете
    failed = runs.get(rid)
    assert failed is not None and failed.error_code == "budget_exhausted"
    assert runs.count_by_status().get("queued") == 1

    stuck = runs.create(kind="insight", mode="pipeline", company_id=COMPANY, event_id=event_id)
    assert runs.start(stuck)
    app.db.execute("UPDATE agent_runs SET started_at = '2020-01-01T00:00:00Z' WHERE id = ?", (stuck,))
    assert runner.recover_stale() == 1
    assert runs.get(stuck).error_code == "interrupted"  # type: ignore[union-attr]
