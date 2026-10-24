from __future__ import annotations

import threading

from alfa_insight.agent.context import AgentContext, AgentLimits
from alfa_insight.agent.trace import TraceWriter
from alfa_insight.appctx import build_context
from alfa_insight.llm.types import LLMCallRecord
from alfa_insight.settings import Settings
from alfa_insight.store.runs import RunStore
from tests.unit.ranking.helpers import profile


def test_run_lifecycle(settings: Settings) -> None:
    ctx = build_context(settings)
    runs = RunStore(ctx.db)
    a = runs.create(kind="insight", mode="pipeline", company_id="C1", priority="precompute", event_id=None)
    b = runs.create(kind="insight", mode="pipeline", company_id="C1", priority="interactive")
    claimed = runs.claim_next()
    assert claimed is not None and claimed.id == b and claimed.status == "running"
    assert not runs.start(b)  # уже взят
    runs.add_usage(b, tokens_in=100, tokens_out=50, cost_rub=0.2)
    runs.add_usage(b, tokens_in=10, tokens_out=5, cost_rub=0.05)
    runs.succeed(b, insight_id="ins_1", result={"ok": True})
    row = runs.get(b)
    assert row is not None and row.final and row.insight_id == "ins_1" and row.result == {"ok": True}
    assert (row.tokens_in, row.tokens_out, round(row.cost_rub, 4)) == (110, 55, 0.25)
    assert row.duration_ms is not None and row.duration_ms >= 0
    assert runs.claim_next(("interactive",)) is None
    assert runs.start(a)
    assert runs.recover_stale() == 1
    failed = runs.get(a)
    assert failed is not None and (failed.status, failed.error_code) == ("failed", "interrupted")
    assert runs.trace(a)[-1].type == "run.failed"
    runs.fail(b, "internal", "поздно")  # конечный статус не перезаписывается
    assert runs.get(b).status == "succeeded"  # type: ignore[union-attr]
    assert runs.count_by_status() == {"succeeded": 1, "failed": 1}


def test_trace_monotonic_parallel_runs(settings: Settings) -> None:
    ctx = build_context(settings)
    runs = RunStore(ctx.db)
    ids = [runs.create(kind="insight", mode="pipeline", company_id=f"C{i}") for i in range(2)]
    writers = [TraceWriter(ctx.db, rid) for rid in ids]
    n = 60

    def work(w: TraceWriter) -> None:
        for i in range(n):
            w.emit("thought", "tools", f"шаг {i}", payload={"i": i})

    threads = [threading.Thread(target=work, args=(w,)) for w in writers for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for rid in ids:
        seqs = [e.seq for e in runs.trace(rid)]
        assert seqs == list(range(1, 2 * n + 1))
    # продолжение трассы после перезапуска — с последнего seq
    w2 = TraceWriter(ctx.db, ids[0])
    assert w2.emit("run.completed", "finalize", "Готово") == 2 * n + 1
    assert [e.seq for e in runs.trace(ids[0], after_seq=2 * n)] == [2 * n + 1]


def test_trace_llm_listener_and_context(settings: Settings) -> None:
    ctx = build_context(settings)
    runs = RunStore(ctx.db)
    rid = runs.create(kind="insight", mode="pipeline", company_id="SYN-DEMO-02", event_id=None)
    actx = AgentContext.create(
        ctx, run_id=rid, kind="insight", mode="pipeline", profile=profile("SYN-DEMO-02", "construction_buildings"),
        role="cfo", event_id=None, limits=AgentLimits(max_evidence=5),
    )  # fmt: skip
    assert actx.allowed_event_ids == set() and actx.evidence.max_items == 5 and not actx.timed_out
    assert AgentLimits.from_app(ctx).max_cost_rub == settings.llm_max_run_cost_rub
    actx.trace.phase("draft", "Пишу разбор")
    base = dict(
        ts="2026-10-22T10:00:00Z",
        budget_day="2026-10-22",
        priority="interactive",
        task="draft",
        model="deepseek",
        tokens_in=1200,
        tokens_out=400,
        cost_rub=0.05,
        latency_ms=900,
    )
    actx.trace.on_llm_call(LLMCallRecord(run_id=rid, status="ok", cached=False, **base))  # type: ignore[arg-type]
    actx.trace.on_llm_call(LLMCallRecord(run_id="run_other", status="ok", cached=False, **base))  # type: ignore[arg-type]
    actx.trace.on_llm_call(LLMCallRecord(run_id=rid, status="ok", cached=True, **base))  # type: ignore[arg-type]
    events = runs.trace(rid)
    assert [e.type for e in events] == ["phase.started", "llm.call", "llm.call"]
    assert events[1].title == "DeepSeek-V4.1-Flash · черновик" and events[1].phase == "draft"
    assert events[2].title.endswith("из кеша") and events[1].cost_rub == 0.05
