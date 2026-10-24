"""Телеметрия интерфейса и заявки на продукты (имитация) (docs/09-api.md §4.7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from alfa_insight.api.deps import current_session, get_ctx, rate_limit
from alfa_insight.api.schemas import LeadIn, LeadOut, UiEventIn
from alfa_insight.api.session import SessionData
from alfa_insight.appctx import AppContext
from alfa_insight.errors import NotFoundError
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.telemetry import LeadStore, UiEventStore

router = APIRouter(tags=["telemetry"])
LEAD_MESSAGE = "Демо: заявка сохранена, в реальном сервисе с вами свяжется менеджер"


@router.post(
    "/ui-events", status_code=204, response_class=Response, dependencies=[Depends(rate_limit("write"))]
)
async def post_ui_event(
    body: UiEventIn, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> Response:
    UiEventStore(ctx.db).add(
        session_id=s.sid,
        company_id=s.company_id,
        type=body.type,
        insight_id=body.insight_id,
        payload=body.payload,
    )
    return Response(status_code=204)


@router.post("/leads", response_model=LeadOut, dependencies=[Depends(rate_limit("write"))])
async def post_lead(
    body: LeadIn, s: SessionData = Depends(current_session), ctx: AppContext = Depends(get_ctx)
) -> LeadOut:
    product = ctx.products.get(body.product_id)
    if product is None:
        raise NotFoundError("Продукт не найден", {"product_id": body.product_id})
    if body.insight_id is not None:
        row = InsightStore(ctx.db).get(body.insight_id)
        if row is None or row.company_id != s.company_id:
            raise NotFoundError("Инсайт не найден", {"insight_id": body.insight_id})
    lead_id = LeadStore(ctx.db).add(
        company_id=s.company_id,
        session_id=s.sid,
        product_id=product.id,
        insight_id=body.insight_id,
        comment=body.comment,
    )
    return LeadOut(id=lead_id, product_name=product.name, message=LEAD_MESSAGE)
