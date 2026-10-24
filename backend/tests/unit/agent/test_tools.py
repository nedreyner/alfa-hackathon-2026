from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from alfa_insight.agent.context import AgentContext, AgentLimits
from alfa_insight.agent.tools import (
    MAX_RESULT_CHARS,
    TOOLS,
    ToolResult,
    execute_tool_call,
    result_for_model,
    tool_specs,
    tools_for,
)
from alfa_insight.ingest.macro import load_snapshot
from alfa_insight.llm.types import ToolCall
from alfa_insight.store.events import EventStore
from alfa_insight.store.macro import MacroStore
from alfa_insight.store.research import ResearchStore
from alfa_insight.store.runs import RunStore
from alfa_insight.text.lemmatizer import lemmas_str


def _metal_event(app) -> int:  # type: ignore[no-untyped-def]
    events = EventStore(app.db)
    sigs = events.load_signals(events.list_ids())
    best = max(
        (s for s in sigs if any(i.industry_id == "metallurgy" for i in s.industries)),
        key=lambda s: (s.publisher_count, s.importance),
    )
    return best.event_id


def _ctx(
    app, company_id: str = "SYN-DEMO-01", event_id: int | None = None, kind: str = "insight", **lim: Any
):  # type: ignore[no-untyped-def]
    run_id = RunStore(app.db).create(kind=kind, mode="agentic", company_id=company_id, event_id=event_id)
    return AgentContext.create(
        app, run_id=run_id, kind=kind, mode="agentic", profile=app.profiles.get(company_id),  # type: ignore[arg-type]
        role="cfo", event_id=event_id, limits=AgentLimits(**lim),
    )  # fmt: skip


def call(ctx: AgentContext, name: str, **args: Any) -> ToolResult:
    return asyncio.run(execute_tool_call(ctx, ToolCall(id="c1", name=name, arguments=args)))


def test_registry_and_specs() -> None:
    assert set(tools_for("insight")) == {
        "get_event", "get_company_profile", "compute_exposure", "get_counterparties", "search_news",
        "search_alfa_research", "get_macro", "get_related_group", "submit_insight",
    }  # fmt: skip
    assert "open_evidence" in tools_for("chat") and "submit_insight" not in tools_for("chat")
    specs = {s.name: s for s in tool_specs(tools_for("insight"))}
    assert specs["get_counterparties"].parameters["properties"]["limit"] == {
        "type": "integer", "default": 5, "minimum": 1, "maximum": 10,
    }  # fmt: skip
    assert "headline" in specs["submit_insight"].parameters["properties"]
    assert all(TOOLS[n].description for n in TOOLS)


def test_event_profile_exposure(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    eid = _metal_event(seeded_ctx)
    ctx = _ctx(seeded_ctx, event_id=eid)
    ev = call(ctx, "get_event", event_id=eid)
    assert ev.ok and ev.evidence and all(e.source_id.startswith("news:") for e in ev.evidence)
    assert ev.evidence[0].eid == "E1" and ev.data["industries"] and "важность" in ev.summary
    assert len(ev.evidence) <= 5 and ev.evidence[0].untrusted

    prof = call(ctx, "get_company_profile")
    [p] = prof.evidence
    assert p.source_id == "data:SYN-DEMO-01:profile" and p.kind == "client_data" and not p.untrusted
    assert (
        "ТД Северный Металл" in p.text
        and "suppliers.metallurgy" in p.text
        and "Закупки по отраслям" in p.text
    )

    exp = call(ctx, "compute_exposure", event_id=eid)
    assert exp.ok and exp.evidence and ctx.exposure is not None and ctx.exposure.event_id == eid
    first = exp.evidence[0]
    assert first.source_id.startswith(f"data:SYN-DEMO-01:exposure:{eid}:")
    assert first.meta["path_id"] == "P1" and ctx.path_eids["P1"] == first.eid
    assert (
        "Сила связи:" in first.text
        and "0." not in first.text.split("Сила связи:")[1][:12]
        and "Путей влияния" in exp.summary
    )
    supply = [e for e in exp.evidence if e.meta["channel"] == "supply"]
    assert supply and "доля закупок" in supply[0].text

    # повтор не дублирует evidence
    again = call(ctx, "get_event", event_id=eid)
    assert [e.eid for e in again.evidence] == [e.eid for e in ev.evidence]
    types = [t.type for t in RunStore(seeded_ctx.db).trace(ctx.run_id)]
    assert types.count("tool.call") == 4 and types.count("tool.result") == 4 and "evidence.added" in types
    assert ctx.tool_calls == 4


def test_counterparties_group_macro(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(seeded_ctx)
    cp = call(ctx, "get_counterparties", direction="suppliers", industry_id="metallurgy", limit=3)
    assert cp.ok and cp.evidence[0].source_id == "data:SYN-DEMO-01:supply:metallurgy"
    assert "Доля отрасли в закупках" in cp.evidence[0].text and len(cp.data["counterparties"]) <= 3
    allb = call(ctx, "get_counterparties", direction="buyers")
    assert allb.evidence[0].source_id == "data:SYN-DEMO-01:demand:all"

    grp = call(ctx, "get_related_group")
    assert grp.ok
    if grp.evidence:
        assert grp.evidence[0].source_id == "data:SYN-DEMO-01:group"

    load_snapshot(MacroStore(seeded_ctx.db), seeded_ctx.settings.seed_dir / "macro.json")
    rate = call(ctx, "get_macro", indicator="key_rate")
    [r] = rate.evidence
    assert r.source_id.startswith("cbr:key_rate:20") and r.kind == "cbr" and r.numbers
    assert "Ключевая ставка Банка России на" in r.text and rate.data["series"]
    fx = call(ctx, "get_macro", indicator="fx", currency="CNY", days=30)
    assert fx.evidence[0].source_id.startswith("cbr:fx_cny:") and "юаня" in fx.evidence[0].text
    bad = call(ctx, "get_macro", indicator="fx")
    assert not bad.ok and "currency" in (bad.error or "")
    titles = [t.title for t in RunStore(seeded_ctx.db).trace(ctx.run_id) if t.type == "tool.call"]
    assert "Проверяю курс CNY" in titles and "Проверяю ключевую ставку" in titles


def test_search_news_extends_scope(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(seeded_ctx, event_id=None)
    res = call(ctx, "search_news", query="выплавка стали металлургия", days=60, limit=3)
    assert res.ok and res.evidence and all(e.kind == "news" for e in res.evidence)
    found = {r["event_id"] for r in res.data["results"]} - {None}
    assert found and found <= ctx.allowed_event_ids
    eid = next(iter(found))
    assert call(ctx, "get_event", event_id=eid).ok
    empty = call(ctx, "search_news", query="квазитерминологический абсурд")
    assert empty.ok and not empty.evidence and "не найдено" in empty.summary


def test_research(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    store = ResearchStore(seeded_ctx.db)
    doc = store.create_doc(
        slug="metals",
        title="Металлы: обзор",
        published_at="2026-10-10",
        file_name="m.pdf",
        sha256="m",
        pages=3,
        url=None,
    )
    text = "Мы ожидаем роста цен на арматуру на 5–7% в четвёртом квартале на фоне ремонтов."
    cid = store.add_chunk(
        doc, source_id="alfa:metals:p3:c1", page=3, chunk_no=1, kind="text", heading="Сталь",
        text=text, heading_lemmas=lemmas_str("Сталь"), text_lemmas=lemmas_str(text),
    )  # fmt: skip
    store.add_items(
        cid,
        [
            {
                "kind": "forecast",
                "statement": "рост цен на арматуру",
                "industries": ["metallurgy"],
                "factors": [],
                "confidence": 0.8,
            }
        ],
    )
    ctx = _ctx(seeded_ctx)
    res = call(ctx, "search_alfa_research", query="цены на арматуру", industry_ids=["metallurgy"])
    [e] = res.evidence
    assert e.source_id == "alfa:metals:p3:c1" and e.kind == "alfa" and e.untrusted
    assert e.title == "Металлы: обзор, с. 3" and e.publisher == "Альфа-Банк" and "Ключевые тезисы" in e.text
    none = call(ctx, "search_alfa_research", query="криптовалюта майнинг")
    assert none.ok and "нет материалов" in none.summary


def test_scope_and_limits(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    eid = _metal_event(seeded_ctx)
    ctx = _ctx(seeded_ctx, event_id=eid, max_tool_calls=4)
    other = max(EventStore(seeded_ctx.db).list_ids())
    other = other if other != eid else other - 1
    r = call(ctx, "get_event", event_id=other)
    assert not r.ok and r.error == f"Событие {other} недоступно в этом разборе"
    r = call(ctx, "get_counterparties", direction="suppliers", industry_id="steel")
    assert not r.ok and "Неизвестная отрасль" in (r.error or "")
    r = call(ctx, "search_alfa_research", query="ставка", factor_ids=["moon"])
    assert not r.ok and "Неизвестный фактор" in (r.error or "")
    r = call(ctx, "get_counterparties", direction="sideways")
    assert not r.ok and (r.error or "").startswith("Неверные аргументы")
    r = call(ctx, "get_event", event_id=eid)
    assert not r.ok and "Лимит" in (r.error or "")
    r = call(ctx, "open_evidence", eid="E1")
    assert not r.ok and "недоступен" in (r.error or "")
    r = call(ctx, "no_such_tool")
    assert not r.ok
    r = asyncio.run(
        execute_tool_call(ctx, ToolCall(id="x", name="submit_insight", arguments={"__raw__": "{"}))
    )
    assert not r.ok and "JSON" in (r.error or "")
    # чужая компания: событие пользователя другой компании недоступно и через allowed_event_ids
    assert ctx.company_id == "SYN-DEMO-01"


def test_private_event_of_other_company(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    from alfa_insight.store.news import NewsIn, NewsStore
    from alfa_insight.timeutil import to_iso, utc_now

    now = to_iso(utc_now())
    [nid] = NewsStore(seeded_ctx.db).insert(
        [NewsIn(source_id="user", origin="user", title="Наш контракт", body="текст", body_source="user",
                publisher="Пользователь", trust=0.5, published_at=now, fetched_at=now, status="tagged",
                owner_company_id="SYN-DEMO-02")]
    )  # fmt: skip
    ev = EventStore(seeded_ctx.db).create(nid, visibility="private", owner_company_id="SYN-DEMO-02")
    mine = _ctx(seeded_ctx, company_id="SYN-DEMO-02", event_id=ev, kind="analyze")
    res = call(mine, "get_event", event_id=ev)
    assert res.ok and res.evidence[0].source_id == f"user:{nid}" and res.evidence[0].kind == "user_input"
    stranger = _ctx(seeded_ctx, company_id="SYN-DEMO-01", event_id=ev)  # даже если id попал в контекст
    assert not call(stranger, "get_event", event_id=ev).ok


def test_result_for_model_truncation() -> None:
    from alfa_insight.agent.evidence import EvidenceRegistry

    reg = EvidenceRegistry()
    items = [
        reg.add(source_id=f"news:{i}", kind="news", title=f"Новость {i}", text="длинный текст " * 200)
        for i in range(8)
    ]
    res = ToolResult(ok=True, summary="Найдено 8", evidence=items, data={"x": list(range(500))})
    text = result_for_model(res)
    body = json.loads(text)
    assert len(text) <= MAX_RESULT_CHARS and body["truncated"] is True
    assert body["evidence"][0]["text"].startswith('<untrusted_document id="E1" kind="news">')
    small = json.loads(result_for_model(ToolResult(ok=True, summary="ok", evidence=items[:1])))
    assert "truncated" not in small and small["evidence"][0]["eid"] == "E1"
    err = json.loads(result_for_model(ToolResult(ok=False, summary="x", error="Событие 991 недоступно")))
    assert err == {"ok": False, "error": "Событие 991 недоступно"}


@pytest.mark.parametrize("n", [1])
def test_open_evidence_chat(seeded_ctx, n: int) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(seeded_ctx, kind="chat")
    ctx.evidence.add(source_id="news:1", kind="news", title="T", text="А" * 3000)
    r = call(ctx, "open_evidence", eid="E1")
    assert r.ok and len(r.data["text"]) > 2500 and r.data["text"].startswith("<untrusted_document")
    assert not call(ctx, "open_evidence", eid="E9").ok
