"""SSE шагов прогона: опрос trace_events раз в 250 мс с Last-Event-ID (docs/09-api.md §5, ADR-15)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request

from alfa_insight.appctx import AppContext
from alfa_insight.store.runs import RunStore

POLL_S = 0.25
MAX_STREAM_S = 300


def end_payload(run: Any) -> dict[str, Any]:
    result = run.result or {}
    return {
        "status": run.status, "insight_id": run.insight_id, "message_id": result.get("message_id"),
        "error_code": run.error_code, "error_message": run.error_message, "duration_ms": run.duration_ms,
        "cost_rub": round(run.cost_rub, 4),
    }  # fmt: skip


async def run_events(
    request: Request,
    ctx: AppContext,
    run_id: str,
    last: int,
    *,
    poll_s: float = POLL_S,
    max_s: float = MAX_STREAM_S,
) -> AsyncIterator[dict[str, Any]]:
    runs = RunStore(ctx.db)
    started = time.monotonic()
    while True:
        events = await asyncio.to_thread(runs.trace, run_id, after_seq=last)
        for e in events:
            last = e.seq
            yield {"id": str(e.seq), "event": "trace", "data": e.model_dump_json()}
        run = await asyncio.to_thread(runs.get, run_id)
        if run is None:
            return
        if run.final and not events:
            # дочитать события, записанные между чтением трассы и статуса
            tail = await asyncio.to_thread(runs.trace, run_id, after_seq=last)
            for e in tail:
                last = e.seq
                yield {"id": str(e.seq), "event": "trace", "data": e.model_dump_json()}
            yield {"event": "end", "data": json.dumps(end_payload(run), ensure_ascii=False)}
            return
        if await request.is_disconnected() or time.monotonic() - started > max_s:
            return
        if not events:
            await asyncio.sleep(poll_s)
