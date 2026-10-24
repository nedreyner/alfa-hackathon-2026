"""Генерация по событию, фича B, статус прогона и SSE, чат (docs/09-api.md §4.4–4.6, §5)."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Query, Request, Response
from sse_starlette.sse import EventSourceResponse

from alfa_insight.agent.intake import AnalyzeInput
from alfa_insight.agent.schemas import ChatAnswer, SourceRef
from alfa_insight.api.deps import current_session, get_ctx, get_runner, rate_limit
from alfa_insight.api.routes.insights import run_info, visible_event
from alfa_insight.api.schemas import (
    AnalyzeHistoryItem,
    ChatIn,
    ChatMessageOut,
    ChatStartResponse,
    ChatThreadResponse,
    GenerateResponse,
    RunInfo,
    RunRef,
)
from alfa_insight.api.session import SessionData
from alfa_insight.api.sse import run_events
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.net.safe_fetch import validate_url
from alfa_insight.services.insights import get_insight
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.chat import ChatStore
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.runs import RunRow, RunStore
from alfa_insight.timeutil import parse_dt

router = APIRouter(tags=["runs"])
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def own_run(ctx: AppContext, run_id: str, company_id: str) -> RunRow:
    run = RunStore(ctx.db).get(run_id)
    if run is None or run.company_id != company_id:
        raise NotFoundError("Прогон не найден", {"run_id": run_id})
    return run


@router.post(
    "/events/{event_id}/insight", response_model=GenerateResponse, status_code=202,
    dependencies=[Depends(rate_limit("generate"))], responses={200: {"model": GenerateResponse}},
)  # fmt: skip
async def generate_insight(
    event_id: int, response: Response, s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx), runner: JobRunner = Depends(get_runner),
) -> GenerateResponse:  # fmt: skip
    visible_event(ctx, event_id, s.company_id)
    res = runner.start_interactive(s.company_id, s.role, event_id, session_id=s.sid)
    if res.status == "ready":
        response.status_code = 200
    return GenerateResponse(status=res.status, insight_id=res.insight_id, run_id=res.run_id)


@router.post(
    "/analyze", response_model=RunRef, status_code=202, dependencies=[Depends(rate_limit("analyze"))]
)
async def analyze(
    body: AnalyzeInput, s: SessionData = Depends(current_session), runner: JobRunner = Depends(get_runner)
) -> RunRef:
    """Ошибки загрузки и извлечения приходят в SSE (run.failed); небезопасный URL отсекается сразу."""
    if body.url is not None:
        validate_url(str(body.url))
    return RunRef(run_id=runner.start_analyze(s.company_id, s.role, body, session_id=s.sid))


def _input_label(run: RunRow) -> str:
    url = run.input.get("url")
    if url:
        return (urlsplit(str(url)).hostname or str(url)).removeprefix("www.")
    text = str(run.input.get("title") or run.input.get("text") or "")
    return text[:80] + ("…" if len(text) > 80 else "")


@router.get("/analyze/history", response_model=list[AnalyzeHistoryItem])
async def analyze_history(
    limit: int = Query(default=10, ge=1, le=50), s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> list[AnalyzeHistoryItem]:  # fmt: skip
    store = InsightStore(ctx.db)
    out = []
    for run in RunStore(ctx.db).list_for_company(s.company_id, "analyze", limit=limit):
        ins = store.get(run.insight_id) if run.insight_id else None
        out.append(
            AnalyzeHistoryItem(
                run_id=run.id, created_at=parse_dt(run.created_at), status=run.status, input_label=_input_label(run),
                insight_id=run.insight_id, headline=ins.headline if ins else None,
            )
        )  # fmt: skip
    return out


@router.get("/runs/{run_id}", response_model=RunInfo)
async def get_run(
    run_id: str, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> RunInfo:
    return run_info(ctx, own_run(ctx, run_id, s.company_id))


@router.get("/runs/{run_id}/events", response_class=EventSourceResponse)
async def run_events_stream(
    run_id: str,
    request: Request,
    s: SessionData = Depends(current_session),
    ctx: AppContext = Depends(get_ctx),
) -> EventSourceResponse:
    own_run(ctx, run_id, s.company_id)
    raw = request.headers.get("last-event-id", "0")
    last = int(raw) if raw.isdigit() else 0
    return EventSourceResponse(run_events(request, ctx, run_id, last), ping=15, headers=SSE_HEADERS)


# ── чат ──
@router.post(
    "/insights/{insight_id}/chat", response_model=ChatStartResponse, status_code=202,
    dependencies=[Depends(rate_limit("chat"))],
)  # fmt: skip
async def chat_ask(
    insight_id: str,
    body: ChatIn,
    s: SessionData = Depends(current_session),
    runner: JobRunner = Depends(get_runner),
) -> ChatStartResponse:
    run_id, thread_id, message_id = runner.start_chat(
        s.company_id, s.role, insight_id, body.message, session_id=s.sid, thread_id=body.thread_id
    )
    return ChatStartResponse(run_id=run_id, thread_id=thread_id, user_message_id=message_id)


@router.get("/insights/{insight_id}/chat", response_model=ChatThreadResponse)
async def chat_thread(
    insight_id: str, thread_id: str | None = Query(default=None, max_length=64),
    s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx),
) -> ChatThreadResponse:  # fmt: skip
    get_insight(ctx, insight_id, s.company_id)
    chat = ChatStore(ctx.db)
    thread = thread_id or chat.last_thread(insight_id, s.sid)
    if thread is None:
        return ChatThreadResponse(thread_id=None, messages=[])
    owner = chat.thread_owner(thread)
    if owner is None or owner[0] != insight_id or owner[1] != s.company_id:
        raise NotFoundError("Тред не найден", {"thread_id": thread})
    store = InsightStore(ctx.db)
    out = []
    for m in chat.thread(thread):
        answer = ChatAnswer.model_validate(m["content"]) if m["role"] == "assistant" else None
        sources = []
        if answer is not None:
            for sid in dict.fromkeys(r for b in answer.blocks for r in b.refs):
                src = store.source(sid, company_id=s.company_id)
                if src is not None:
                    sources.append(SourceRef(id=src.id, kind=src.kind, title=src.title, publisher=src.publisher, url=src.url,  # type: ignore[arg-type]
                                             published_at=parse_dt(src.published_at) if src.published_at else None))  # fmt: skip
        out.append(
            ChatMessageOut(
                id=m["id"], role=m["role"], text=m["content"].get("text") if m["role"] == "user" else None,
                answer=answer, sources=sources, created_at=parse_dt(m["created_at"]),
            )
        )  # fmt: skip
    return ChatThreadResponse(thread_id=thread, messages=out)
