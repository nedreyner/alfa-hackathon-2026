from __future__ import annotations

import asyncio

import pytest

from alfa_insight.agent.schemas import ChatAnswer
from alfa_insight.errors import NotFoundError
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.chat import ChatStore
from alfa_insight.store.runs import RunStore
from tests.integration.test_agent_pipeline import COMPANY, metal_event


@pytest.fixture
def app_insight(seeded_ctx):  # type: ignore[no-untyped-def]
    backend = FakeBackend()
    seeded_ctx.set_router(build_router(seeded_ctx.settings, seeded_ctx.db, backend=backend))
    runner = JobRunner(seeded_ctx)

    async def make() -> str:
        res = runner.start_interactive(COMPANY, "cfo", metal_event(seeded_ctx))
        await runner.wait_all()
        return RunStore(seeded_ctx.db).get(res.run_id).insight_id  # type: ignore[union-attr,return-value]

    insight_id = asyncio.run(make())
    return seeded_ctx, runner, backend, insight_id


def ask(runner: JobRunner, insight_id: str, text: str, thread: str | None = None, company: str = COMPANY):  # type: ignore[no-untyped-def]
    async def go():  # type: ignore[no-untyped-def]
        run_id, thread_id, mid = runner.start_chat(
            company, "cfo", insight_id, text, session_id="s1", thread_id=thread
        )
        await runner.wait_all()
        return run_id, thread_id, mid

    run_id, thread_id, _mid = asyncio.run(go())
    run = RunStore(runner.app.db).get(run_id)
    assert run is not None and run.status == "succeeded", (run.error_code, run.error_message) if run else None
    msg = ChatStore(runner.app.db).get(run.result["message_id"])  # type: ignore[index]
    return thread_id, ChatAnswer.model_validate(msg["content"]), run  # type: ignore[index]


def test_answer_refs_are_source_ids(app_insight) -> None:  # type: ignore[no-untyped-def]
    app, runner, backend, insight_id = app_insight
    thread, ans, run = ask(runner, insight_id, "Почему это важно для нас?")
    assert thread.startswith("thr_") and ans.blocks and ans.followups
    refs = [r for b in ans.blocks for r in b.refs]
    assert refs and all(":" in r and not r.startswith("E") for r in refs)
    types = [t.type for t in RunStore(app.db).trace(run.id)]
    assert types[0] == "run.started" and types[-1] == "run.completed" and "verify.report" in types

    # инструмент в чате и запоминание треда
    thread2, ans2, _ = ask(runner, insight_id, "А кто наши крупнейшие контрагенты-поставщики?", thread=thread)
    assert thread2 == thread and any(
        r.startswith(f"data:{COMPANY}:supply:") for b in ans2.blocks for r in b.refs
    )
    chat_calls = [p for task, p in backend.calls if task == "chat"]
    last_msgs = chat_calls[-1]["messages"]
    texts = [m.get("content") or "" for m in last_msgs]
    assert any("Почему это важно для нас?" in t for t in texts)  # история треда в запросе
    assert [m["role"] for m in ChatStore(app.db).thread(thread)] == ["user", "assistant", "user", "assistant"]


def test_wrong_number_block_removed(app_insight) -> None:  # type: ignore[no-untyped-def]
    _app, runner, _backend, insight_id = app_insight
    _, ans, _ = ask(runner, insight_id, "Сколько процентов рост? [[WRONGNUM]]")
    assert all("99,7%" not in b.text for b in ans.blocks) and ans.blocks
    _, ans, run = ask(runner, insight_id, "Совсем плохой ответ [[ALLBAD]]")
    assert len(ans.blocks) == 1 and ans.blocks[0].type == "ai" and "Не могу ответить" in ans.blocks[0].text
    report = next(t for t in RunStore(runner.app.db).trace(run.id) if t.type == "verify.report")
    assert report.status == "warn" and report.payload["removed"] == 1


def test_foreign_insight_and_thread(app_insight) -> None:  # type: ignore[no-untyped-def]
    _app, runner, _backend, insight_id = app_insight
    with pytest.raises(NotFoundError):
        runner.start_chat("SYN-DEMO-01", "cfo", insight_id, "Вопрос", session_id="x")
    thread, _, _ = ask(runner, insight_id, "Первый вопрос")
    with pytest.raises(NotFoundError):
        runner.start_chat(COMPANY, "cfo", "ins_unknown", "Вопрос", session_id="s1", thread_id=thread)
