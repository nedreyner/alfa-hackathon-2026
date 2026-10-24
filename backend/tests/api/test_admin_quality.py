from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from alfa_insight.api.app import create_app
from alfa_insight.ingest.macro import load_snapshot
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.runs import RunStore
from tests.integration.test_agent_pipeline import metal_event

COMPANY = "SYN-DEMO-02"


@pytest.fixture
def env(seeded_ctx) -> Iterator[tuple[TestClient, str]]:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    app.settings.admin_token = type(app.settings.admin_token)("adm-secret")
    load_snapshot(MacroStore(app.db), app.settings.seed_dir / "macro.json")
    app.ranking.rank_company(COMPANY)
    runner = JobRunner(app)

    async def make() -> str:
        res = runner.start_interactive(COMPANY, "cfo", metal_event(app))
        await runner.wait_all()
        return RunStore(app.db).get(res.run_id).insight_id  # type: ignore[union-attr,return-value]

    insight_id = asyncio.run(make())
    app.db.execute("UPDATE insights SET status = 'needs_review' WHERE id = ?", (insight_id,))
    with TestClient(create_app(app, run_worker=False)) as c:
        assert c.post("/api/session", json={"company_id": COMPANY, "role": "cfo"}).status_code == 200
        yield c, insight_id


def test_macro_and_quality(env) -> None:  # type: ignore[no-untyped-def]
    c, insight_id = env
    m = c.get("/api/macro").json()
    assert m["key_rate"]["indicator"] == "key_rate" and len(m["fx"]) == 7 and m["updated_at"]
    c.post("/api/ui-events", json={"type": "insight_open", "insight_id": insight_id})
    c.post("/api/ui-events", json={"type": "source_open", "insight_id": insight_id})
    c.post(f"/api/insights/{insight_id}/feedback", json={"useful": False, "reason": "too_generic"})
    q = c.get("/api/quality").json()
    assert q["online"]["useful_rate"] == 0.0 and q["online"]["negative_reasons"] == {"too_generic": 1}
    assert q["online"]["source_ctr"] == 1.0 and q["online"]["time_to_insight_ms"]["p50"] is not None
    assert q["verification"]["insights"] == 1 and q["review_queue_size"] == 1 and q["window_days"] == 7
    assert q["budget"]["daily_limit_rub"] > 0 and q["budget"]["mode"] == "normal"


def test_admin_requires_token_and_review(env) -> None:  # type: ignore[no-untyped-def]
    c, insight_id = env
    assert c.get("/api/admin/review-queue").status_code == 404
    assert c.get("/api/admin/review-queue", headers={"X-Admin-Token": "wrong"}).status_code == 404
    h = {"X-Admin-Token": "adm-secret"}
    queue = c.get("/api/admin/review-queue", headers=h).json()
    assert [i["insight_id"] for i in queue] == [insight_id]
    r = c.post(
        f"/api/admin/insights/{insight_id}/review", json={"status": "rejected", "note": "неточно"}, headers=h
    )
    assert r.json()["status"] == "rejected" and r.json()["review_note"] == "неточно"
    assert c.get(f"/api/insights/{insight_id}").status_code == 404  # отклонённый скрыт
    assert c.post("/api/admin/rank/run", headers=h).json()["rows"] > 0
    assert (
        c.post("/api/admin/precompute/run", json={"companies": [COMPANY], "top_k": 1}, headers=h).json()[
            "queued"
        ]
        >= 0
    )
    status = c.get("/api/admin/sources/status", headers=h).json()
    assert status and all(isinstance(v, dict) for v in status.values())
    assert c.post("/api/admin/ingest/run", headers=h).json() == {"started": True}
