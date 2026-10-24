from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from alfa_insight.api.app import create_app
from alfa_insight.ingest.macro import load_snapshot
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore, SourceIn
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.news import NewsIn, NewsStore
from alfa_insight.store.research import ResearchStore
from alfa_insight.store.runs import RunStore
from alfa_insight.text.lemmatizer import lemmas_str
from alfa_insight.timeutil import to_iso, utc_now
from tests.integration.test_agent_pipeline import metal_event

COMPANY = "SYN-DEMO-02"


@pytest.fixture
def env(seeded_ctx) -> Iterator[tuple[TestClient, object, int, str]]:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    load_snapshot(MacroStore(app.db), app.settings.seed_dir / "macro.json")
    app.ranking.rank_all()
    event_id = metal_event(app)
    runner = JobRunner(app)

    async def make() -> str:
        res = runner.start_interactive(COMPANY, "cfo", event_id)
        await runner.wait_all()
        return RunStore(app.db).get(res.run_id).insight_id  # type: ignore[union-attr,return-value]

    insight_id = asyncio.run(make())
    with TestClient(create_app(app, run_worker=False)) as c:
        yield c, app, event_id, insight_id


def all_items(c: TestClient, **params: object) -> list[dict]:  # type: ignore[type-arg]
    """Вся лента по курсору (после диверсификации событие может быть не на первой странице)."""
    out, cursor = [], None
    while True:
        page = c.get(
            "/api/feed", params={"limit": 50, **params, **({"cursor": cursor} if cursor else {})}
        ).json()
        out += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return out


def login(c: TestClient, company: str = COMPANY, role: str = "cfo") -> None:
    assert c.post("/api/session", json={"company_id": company, "role": role}).status_code == 200


def test_feed_statuses_filters_cursor(env) -> None:  # type: ignore[no-untyped-def]
    c, app, event_id, insight_id = env
    login(c)
    first = c.get("/api/feed", params={"limit": 50}).json()
    assert first["total"] > 5 and first["budget_mode"] == "normal"
    items = all_items(c)
    assert len(items) == first["total"]
    ready = [i for i in items if i["status"] == "ready"]
    assert [i["event_id"] for i in ready] == [event_id] and ready[0]["insight_id"] == insight_id
    assert ready[0]["confidence_level"] and not ready[0]["stale"] and ready[0]["source_count"] > 0
    pending = [i for i in items if i["status"] == "pending"]
    queued_ev, failed_ev = pending[0]["event_id"], pending[1]["event_id"]
    runs = RunStore(app.db)
    runs.create(
        kind="insight",
        mode="pipeline",
        company_id=COMPANY,
        role="cfo",
        event_id=queued_ev,
        priority="precompute",
    )
    failed = runs.create(kind="insight", mode="pipeline", company_id=COMPANY, role="cfo", event_id=failed_ev)
    runs.fail(failed, "timeout", "долго")
    by_id = {i["event_id"]: i for i in all_items(c)}
    assert by_id[queued_ev]["status"] == "generating" and by_id[queued_ev]["run_id"]
    assert by_id[failed_ev]["status"] == "failed" and by_id[failed_ev]["run_id"] == failed
    assert by_id[queued_ev]["why_you"] and by_id[queued_ev]["headline"] == by_id[queued_ev]["event_title"]

    # фильтры и курсор
    risk = all_items(c, direction="risk")
    assert risk and all(i["direction"] == "risk" for i in risk)
    high = all_items(c, min_impact="high")
    assert all(i["impact_level"] in ("high", "critical") for i in high)
    p1 = c.get("/api/feed", params={"limit": 2}).json()
    p2 = c.get("/api/feed", params={"limit": 2, "cursor": p1["next_cursor"]}).json()
    assert p1["next_cursor"] and {i["event_id"] for i in p1["items"]}.isdisjoint(
        {i["event_id"] for i in p2["items"]}
    )
    assert [i["event_id"] for i in p1["items"] + p2["items"]] == [i["event_id"] for i in items[:4]]
    assert c.get("/api/feed", params={"cursor": "!!bad"}).status_code == 400

    # правка профиля → инсайт устарел
    c.put("/api/me/profile/overrides", json={"notes": "Новые объекты в Казани"})
    again = {i["event_id"]: i for i in all_items(c)}
    assert again[event_id]["status"] == "ready" and again[event_id]["stale"] is True
    assert c.get(f"/api/insights/{insight_id}").json()["stale"] is True

    brief = c.get("/api/brief").json()
    assert brief["role"] == "cfo" and 1 <= len(brief["items"]) <= 3


def test_insight_endpoints(env) -> None:  # type: ignore[no-untyped-def]
    c, app, event_id, insight_id = env
    login(c)
    d = c.get(f"/api/insights/{insight_id}").json()
    assert d["insight"]["id"] == insight_id and d["my_feedback"] is None and d["stale"] is False
    assert c.get(f"/api/events/{event_id}/insight").json()["insight"]["id"] == insight_id
    other = next(
        i["event_id"]
        for i in c.get("/api/feed", params={"limit": 50}).json()["items"]
        if i["status"] == "pending"
    )
    r = c.get(f"/api/events/{other}/insight")
    assert (
        r.status_code == 404
        and r.json()["error"]["code"] == "insight_not_ready"
        and "run_id" in r.json()["error"]["details"]
    )
    tr = c.get(f"/api/insights/{insight_id}/trace").json()
    assert (
        tr["run"]["status"] == "succeeded"
        and tr["run"]["insight_id"] == insight_id
        and tr["events"][0]["seq"] == 1
    )
    assert tr["run"]["duration_ms"] is not None

    # обратная связь — одна на сессию
    assert (
        c.post(
            f"/api/insights/{insight_id}/feedback", json={"useful": True, "reason": "useful_action"}
        ).status_code
        == 200
    )
    r = c.post(
        f"/api/insights/{insight_id}/feedback",
        json={"useful": False, "reason": "too_generic", "comment": "общо"},
    )
    assert r.json()["useful"] is False
    assert app.db.scalar("SELECT count(*) FROM feedback") == 1
    assert c.get(f"/api/insights/{insight_id}").json()["my_feedback"]["reason"] == "too_generic"
    assert (
        c.post(f"/api/insights/{insight_id}/feedback", json={"useful": True, "reason": "great"}).status_code
        == 422
    )

    # заявки и телеметрия
    assert c.post("/api/leads", json={"product_id": "factoring"}).status_code == 422
    assert c.post("/api/leads", json={"product_id": "factoring", "confirm": False}).status_code == 422
    r = c.post("/api/leads", json={"product_id": "factoring", "confirm": True, "insight_id": insight_id})
    assert r.status_code == 200 and r.json()["product_name"] == "Факторинг" and "Демо" in r.json()["message"]
    assert c.post("/api/leads", json={"product_id": "nope", "confirm": True}).status_code == 404
    assert (
        c.post("/api/ui-events", json={"type": "insight_open", "insight_id": insight_id}).status_code == 204
    )
    assert c.post("/api/ui-events", json={"type": "hack"}).status_code == 422


def test_sources_each_kind(env) -> None:  # type: ignore[no-untyped-def]
    c, app, _event_id, insight_id = env
    login(c)
    ins = c.get(f"/api/insights/{insight_id}").json()["insight"]
    kinds = {s["kind"]: s["id"] for s in ins["sources"]}
    news = c.get(f"/api/sources/{kinds['news']}").json()
    assert news["kind"] == "news" and news["text"] and news["excerpt"]
    data = c.get(f"/api/sources/{kinds['client_data']}").json()
    assert data["kind"] == "client_data" and data["data"] is not None
    supply = [s["id"] for s in ins["sources"] if ":supply:" in s["id"]]
    if supply:
        assert c.get(f"/api/sources/{supply[0]}").json()["data"]["counterparties"]
    store = InsightStore(app.db)
    rs = ResearchStore(app.db)
    doc = rs.create_doc(
        slug="m", title="Металлы", published_at="2026-10-10", file_name="m.pdf", sha256="m", pages=1, url=None
    )
    rs.add_chunk(doc, source_id="alfa:m:p1:c1", page=1, chunk_no=1, kind="text", heading=None, text="Сталь подорожает.",
                 heading_lemmas="", text_lemmas=lemmas_str("Сталь подорожает."))  # fmt: skip
    store.upsert_sources([
        SourceIn(id="alfa:m:p1:c1", kind="alfa", title="Металлы, с. 1", publisher="Альфа-Банк", excerpt="Сталь подорожает."),
        SourceIn(id="cbr:key_rate:2026-10-23", kind="cbr", title="Ключевая ставка", publisher="Банк России", excerpt="14%"),
    ])  # fmt: skip
    alfa = c.get("/api/sources/alfa:m:p1:c1").json()
    assert alfa["doc_title"] == "Металлы" and alfa["page"] == 1 and alfa["text"] == "Сталь подорожает."
    cbr = c.get("/api/sources/cbr:key_rate:2026-10-23").json()
    assert cbr["data"]["indicator"] == "key_rate" and cbr["data"]["series"]
    assert c.get("/api/sources/news:999999").status_code == 404


def test_scope_isolation(env) -> None:  # type: ignore[no-untyped-def]
    c, app, _event_id, insight_id = env
    now = to_iso(utc_now())
    [nid] = NewsStore(app.db).insert(
        [NewsIn(source_id="user", origin="user", title="Наш тендер", body="текст", body_source="user", publisher="Ваш текст",
                trust=0.5, published_at=now, fetched_at=now, status="tagged", owner_company_id=COMPANY)]
    )  # fmt: skip
    private = EventStore(app.db).create(nid, visibility="private", owner_company_id=COMPANY)
    InsightStore(app.db).upsert_sources(
        [
            SourceIn(
                id=f"user:{nid}", kind="user_input", title="Наш тендер", company_id=COMPANY, excerpt="текст"
            )
        ]
    )
    ins = InsightStore(app.db).get(insight_id)
    client_src = next(s for s in ins.payload["sources"] if s["kind"] == "client_data")["id"]  # type: ignore[union-attr]
    login(c, COMPANY)
    assert c.get(f"/api/sources/user:{nid}").status_code == 200
    login(c, "SYN-DEMO-01")
    for path in (
        f"/api/insights/{insight_id}",
        f"/api/insights/{insight_id}/trace",
        f"/api/sources/{client_src}",
        f"/api/sources/user:{nid}",
        f"/api/events/{private}/insight",
    ):
        r = c.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found", path
    assert c.post(f"/api/insights/{insight_id}/feedback", json={"useful": True}).status_code == 404
    assert (
        c.post(
            "/api/leads", json={"product_id": "factoring", "confirm": True, "insight_id": insight_id}
        ).status_code
        == 404
    )


def test_what_if_endpoint(env) -> None:  # type: ignore[no-untyped-def]
    c, _app, _event_id, insight_id = env
    login(c)
    r = c.post(f"/api/insights/{insight_id}/what-if", json={"rate_delta_pp": -1, "fx_delta_pct": 5})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "Вывод ИИ: оценка" and isinstance(body["currencies"], list)
    assert (body["rate"] is not None) == body["rate_available"]
    assert c.post(f"/api/insights/{insight_id}/what-if", json={"rate_delta_pp": 5}).status_code == 422
    login(c, "SYN-DEMO-01")
    assert c.post(f"/api/insights/{insight_id}/what-if", json={}).status_code == 404
