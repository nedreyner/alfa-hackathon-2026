from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from alfa_insight.agent.intake import AnalyzeInput
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.services.insights import current_prompt_version
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.events import EventStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.store.runs import RunStore

COMPANY = "SYN-DEMO-02"
METAL_TEXT = (
    "Крупнейшие металлургические компании России с 1 ноября повышают отпускные цены на арматуру и "
    "строительный прокат на 8%. По словам участников рынка, рост цен на сталь связан с ремонтами "
    "доменных печей и подорожанием угля. Девелоперы и строительные компании уже пересматривают сметы: "
    "арматура занимает заметную долю в себестоимости монолитного строительства. Аналитики ожидают, "
    "что металлопрокат продолжит дорожать до конца года."
)
FOOTBALL_TEXT = (
    "Футбольный клуб из Казани одержал победу в выездном матче чемпионата страны со счётом два на ноль. "
    "Оба гола были забиты во втором тайме после стандартных положений. Тренер команды похвалил игроков "
    "за дисциплину в обороне и отметил вклад молодых футболистов. Следующий матч команда проведёт дома "
    "через неделю, билеты уже поступили в продажу на сайте клуба."
)
HTML = f"<html><head><title>Арматура подорожает на 8%</title></head><body><article><h1>Арматура подорожает на 8%</h1><p>{METAL_TEXT}</p><p>{METAL_TEXT}</p></article></body></html>"


def resolver(_mapping: dict[str, list[str]] | None = None):  # type: ignore[no-untyped-def]
    async def resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    return resolve


def transport(handler: Any) -> dict[str, Any]:
    return {"transport": httpx.MockTransport(handler), "resolver": resolver(), "pin_ip": False}


def html_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=HTML.encode())


@pytest.fixture
def app(seeded_ctx):  # type: ignore[no-untyped-def]
    backend = FakeBackend()
    seeded_ctx.set_router(build_router(seeded_ctx.settings, seeded_ctx.db, backend=backend))
    seeded_ctx.fake_backend = backend
    return seeded_ctx


def analyze(app, inp: AnalyzeInput, **fetch: Any):  # type: ignore[no-untyped-def]
    runner = JobRunner(app, fetch_options=fetch)

    async def go() -> str:
        rid = runner.start_analyze(COMPANY, "cfo", inp, session_id="s")
        await runner.wait_all()
        return rid

    run = RunStore(app.db).get(asyncio.run(go()))
    assert run is not None
    return run, RunStore(app.db).trace(run.id)


def test_two_rounds_to_insight(app) -> None:  # type: ignore[no-untyped-def]
    run, trace = analyze(
        app, AnalyzeInput(text=METAL_TEXT, title="Металлурги поднимают цены на арматуру на 8%")
    )
    assert run.status == "succeeded", (run.error_code, run.error_message)
    types = [t.type for t in trace]
    assert types[0] == "run.started" and trace[0].phase == "intake"
    assert {
        "intake.extract",
        "intake.tagged",
        "plan",
        "tool.call",
        "draft.ready",
        "verify.report",
        "run.completed",
    } <= set(types)
    start = next(i for i, t in enumerate(trace) if t.type == "phase.started" and t.title == "Исследую тему")
    prefetch = [t.payload["tool"] for t in trace[:start] if t.type == "tool.call"]
    assert prefetch[:4] == ["get_event", "get_company_profile", "compute_exposure", "search_alfa_research"]
    model_tools = [t.payload["tool"] for t in trace[start:] if t.type == "tool.call"]
    assert model_tools[:2] == ["search_alfa_research", "get_macro"] and "submit_insight" in model_tools
    plans = [t.payload["text"] for t in trace if t.type == "plan"]
    assert any("аналитиков банка" in p for p in plans)
    ev = EventStore(app.db).get(run.event_id)
    assert ev is not None and ev.visibility == "private" and ev.owner_company_id == COMPANY
    assert RankingStore(app.db).get(COMPANY, ev.id, "cfo") is not None
    ins = InsightStore(app.db).get(run.insight_id)
    assert (
        ins is not None
        and ins.prompt_version == f"{app.prompts.version('agent')}+{app.prompts.version('verify')}"
        and ins.payload["event"]["visibility"] == "private"
    )
    assert any(s["id"].startswith("user:") for s in ins.payload["sources"])
    agent_calls = [p for task, p in app.fake_backend.calls if task == "agent"]
    assert len(agent_calls) == 2 and agent_calls[1]["messages"][-1]["role"] == "tool"


def test_bad_submit_is_fixed(app) -> None:  # type: ignore[no-untyped-def]
    run, trace = analyze(app, AnalyzeInput(text=METAL_TEXT + " [[BADSUBMIT]]"))
    assert run.status == "succeeded"
    results = [t for t in trace if t.type == "tool.result" and t.payload["tool"] == "submit_insight"]
    assert not results[0].payload["ok"] and results[-1].payload["ok"]
    assert "Неверные аргументы" in results[0].title


def test_forced_submit_and_no_tools(app, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    run, trace = analyze(app, AnalyzeInput(text=METAL_TEXT + " [[NOSUBMIT]]"))
    assert run.status == "succeeded"
    forced = [
        p for task, p in app.fake_backend.calls if task == "agent" and isinstance(p.get("tool_choice"), dict)
    ]
    assert forced and forced[0]["tool_choice"]["function"]["name"] == "submit_insight"

    monkeypatch.setattr("alfa_insight.agent.agentic_mode.tools_supported", lambda ctx: False)
    run, trace = analyze(app, AnalyzeInput(text=METAL_TEXT.replace("8%", "9%")))
    assert run.status == "succeeded"
    assert any("пакетный режим" in t.title for t in trace if t.type == "plan")
    assert InsightStore(app.db).get(run.insight_id).prompt_version == current_prompt_version(app)  # type: ignore[union-attr]


def test_intake_url_reuse_and_errors(app) -> None:  # type: ignore[no-untyped-def]
    url = "https://news.example/metal/armatura"
    run1, trace1 = analyze(app, AnalyzeInput(url=url), **transport(html_ok))
    assert run1.status == "succeeded", (run1.error_code, run1.error_message)
    assert any(t.type == "intake.fetch" and "news.example" in t.title for t in trace1)
    run2, trace2 = analyze(app, AnalyzeInput(url=url), **transport(html_ok))
    assert run2.status == "succeeded" and run2.event_id == run1.event_id
    assert any(t.type == "intake.fetch" and t.payload.get("reused") for t in trace2)

    bad, _ = analyze(
        app, AnalyzeInput(url="https://news.example/500"), **transport(lambda r: httpx.Response(500))
    )
    assert (bad.status, bad.error_code) == ("failed", "fetch_failed")
    short = "<html><body><p>Коротко.</p></body></html>"
    tiny, _ = analyze(
        app, AnalyzeInput(url="https://news.example/short"),
        **transport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, content=short.encode())),
    )  # fmt: skip
    assert (tiny.status, tiny.error_code) == ("failed", "unsupported_content")
    blocked, _ = analyze(app, AnalyzeInput(url="http://127.0.0.1/admin"), **transport(html_ok))
    assert blocked.error_code == "blocked_url"


def test_weak_relevance_note(app) -> None:  # type: ignore[no-untyped-def]
    run, _ = analyze(app, AnalyzeInput(text=FOOTBALL_TEXT))
    assert run.status == "succeeded", (run.error_code, run.error_message)
    first_agent = next(p for task, p in app.fake_backend.calls if task == "agent")
    user = next(m["content"] for m in first_agent["messages"] if m["role"] == "user")
    assert "Связь события с компанией слабая" in user
    assert RankingStore(app.db).get(COMPANY, run.event_id, "cfo") is not None  # даже при слабой связи


def test_analyze_input_validation() -> None:
    with pytest.raises(ValueError):
        AnalyzeInput()
    with pytest.raises(ValueError):
        AnalyzeInput(url="https://a.ru/x", text="т" * 300)  # type: ignore[arg-type]
    assert json.loads(AnalyzeInput(text="т" * 250).model_dump_json())["text"]
