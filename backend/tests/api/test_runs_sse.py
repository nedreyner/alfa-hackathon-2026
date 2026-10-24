from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alfa_insight.api.app import create_app
from tests.integration.test_agent_pipeline import metal_event
from tests.integration.test_agentic import METAL_TEXT

COMPANY = "SYN-DEMO-02"


@pytest.fixture
def c(seeded_ctx) -> Iterator[TestClient]:  # type: ignore[no-untyped-def]
    seeded_ctx.ranking.rank_company(COMPANY)
    with TestClient(create_app(seeded_ctx, run_worker=False)) as client:
        assert client.post("/api/session", json={"company_id": COMPANY, "role": "cfo"}).status_code == 200
        client.app_ctx = seeded_ctx  # type: ignore[attr-defined]
        yield client


def sse(c: TestClient, run_id: str, last: int | None = None) -> list[tuple[str, Any, str | None]]:
    headers = {"Last-Event-ID": str(last)} if last is not None else {}
    out = []
    with c.stream("GET", f"/api/runs/{run_id}/events", headers=headers) as r:
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"
        event, data, eid = None, None, None
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
            elif line.startswith("id:"):
                eid = line.split(":", 1)[1].strip()
            elif line == "" and event:
                out.append((event, data, eid))
                event, data, eid = None, None, None
                if out[-1][0] == "end":
                    break
    return out


def test_generate_and_stream(c: TestClient) -> None:
    event_id = metal_event(c.app_ctx)  # type: ignore[attr-defined]
    r = c.post(f"/api/events/{event_id}/insight")
    assert r.status_code == 202 and r.json()["status"] in ("started", "running") and r.json()["run_id"]
    run_id = r.json()["run_id"]
    events = sse(c, run_id)
    assert events[-1][0] == "end" and events[-1][1]["status"] == "succeeded" and events[-1][1]["insight_id"]
    seqs = [d["seq"] for e, d, _ in events if e == "trace"]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) > 10
    assert [int(i) for e, _, i in events if e == "trace"] == seqs
    # переподключение с Last-Event-ID — без дублей; завершённый прогон отдаёт историю сразу
    tail = sse(c, run_id, last=5)
    assert [d["seq"] for e, d, _ in tail if e == "trace"] == seqs[5:] and tail[-1][0] == "end"
    info = c.get(f"/api/runs/{run_id}").json()
    assert (
        info["status"] == "succeeded"
        and info["insight_id"] == events[-1][1]["insight_id"]
        and info["kind"] == "insight"
    )
    again = c.post(f"/api/events/{event_id}/insight")
    assert again.status_code == 200 and again.json() == {
        "status": "ready",
        "insight_id": info["insight_id"],
        "run_id": None,
    }
    # чужой прогон
    assert c.post("/api/session", json={"company_id": "SYN-DEMO-01", "role": "cfo"}).status_code == 200
    assert c.get(f"/api/runs/{run_id}").status_code == 404
    assert c.get(f"/api/runs/{run_id}/events").status_code == 404


def test_analyze_validation_busy_and_same_run(c: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    r = c.post("/api/analyze", json={"url": "http://127.0.0.1/admin"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "blocked_url"
    assert c.post("/api/analyze", json={"text": "коротко"}).status_code == 422
    assert c.post("/api/analyze", json={}).status_code == 422

    async def slow(ctx, **kw):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1.5)
        raise TimeoutError

    monkeypatch.setattr("alfa_insight.services.jobs.run_agent", slow)
    monkeypatch.setattr(c.app_ctx.settings, "agent_max_concurrent_runs", 2)  # type: ignore[attr-defined]
    event_id = metal_event(c.app_ctx)  # type: ignore[attr-defined]
    first = c.post(f"/api/events/{event_id}/insight").json()
    second = c.post(f"/api/events/{event_id}/insight").json()
    assert second["status"] == "running" and second["run_id"] == first["run_id"]
    a = c.post("/api/analyze", json={"text": METAL_TEXT})
    assert a.status_code == 202
    busy = c.post("/api/analyze", json={"text": METAL_TEXT + " Ещё раз."})
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "busy"
    time.sleep(2.5)
    hist = c.get("/api/analyze/history").json()
    assert hist[0]["run_id"] == a.json()["run_id"] and hist[0]["input_label"].startswith("Крупнейшие")
    events = sse(c, a.json()["run_id"])
    assert events[-1][1]["status"] == "failed" and events[-1][1]["error_code"] == "timeout"


def test_analyze_end_to_end(c: TestClient) -> None:
    r = c.post("/api/analyze", json={"text": METAL_TEXT, "title": "Арматура дорожает"})
    assert r.status_code == 202
    events = sse(c, r.json()["run_id"])
    assert events[-1][1]["status"] == "succeeded"
    assert any(d["type"] == "intake.tagged" for e, d, _ in events if e == "trace")
    ins = c.get(f"/api/insights/{events[-1][1]['insight_id']}").json()["insight"]
    assert ins["event"]["visibility"] == "private"
    # чат по инсайту
    q = c.post(f"/api/insights/{ins['id']}/chat", json={"message": "Почему это важно?"})
    assert q.status_code == 202
    end = sse(c, q.json()["run_id"])[-1][1]
    assert end["status"] == "succeeded" and end["message_id"]
    thread = c.get(f"/api/insights/{ins['id']}/chat").json()
    assert thread["thread_id"] == q.json()["thread_id"] and [m["role"] for m in thread["messages"]] == [
        "user",
        "assistant",
    ]
    assert thread["messages"][1]["answer"]["blocks"] and thread["messages"][1]["sources"]
