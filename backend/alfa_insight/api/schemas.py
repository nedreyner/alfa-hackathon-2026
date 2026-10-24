"""DTO API (docs/09-api.md §4). Переиспользуют доменные модели, без копий."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from alfa_insight.agent.schemas import ChatAnswer, Insight, Level, SourceKind, SourceRef
from alfa_insight.data.models import CompanyProfile, IndustryShare
from alfa_insight.llm.budget import BudgetMode
from alfa_insight.ranking.models import Direction, ImpactLevel, Role


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class RoleInfoOut(BaseModel):
    id: Role
    name: str
    short: str


class MetaResponse(BaseModel):
    version: str
    demo_mode: bool
    llm_mode: Literal["live", "replay", "fake"]
    data_profile: Literal["real", "synthetic"]
    budget_mode: BudgetMode
    roles: list[RoleInfoOut]


class ReadyResponse(BaseModel):
    ready: bool
    checks: dict[str, bool]


class CompanySummary(BaseModel):
    company_id: str
    name: str
    industry_id: str
    industry_name: str
    region_name: str | None
    revenue_bucket: str
    is_demo: bool
    story: str | None
    default_role: Role


class SessionCreate(BaseModel):
    company_id: str = Field(min_length=1, max_length=64)
    role: Role
    jury_code: str | None = Field(default=None, max_length=200)


class SessionUpdate(BaseModel):
    role: Role


class SessionInfo(BaseModel):
    company: CompanySummary
    role: Role
    jury: bool
    demo_mode: bool
    budget_mode: BudgetMode


class RefItem(BaseModel):
    id: str
    name: str


class ReferenceResponse(BaseModel):
    version: str
    industries: list[RefItem]
    factors: list[RefItem]
    countries: list[RefItem]
    event_types: list[RefItem]
    roles: list[RoleInfoOut]
    products: list[RefItem]
    products_disclaimer: str


# ── профиль (§4.2) ──
OverrideFieldName = Literal["industry_id", "ved", "products", "notes"]


class OverrideOut(BaseModel):
    field: OverrideFieldName
    value: Any
    updated_at: datetime


class ProfileResponse(BaseModel):
    profile: CompanyProfile
    overrides: list[OverrideOut]


class CounterpartyOut(BaseModel):
    name: str
    industry_id: str
    industry_name: str
    share: float


class CounterpartiesResponse(BaseModel):
    direction: Literal["suppliers", "buyers"]
    coverage: float
    basis: str
    mix: list[IndustryShare]
    items: list[CounterpartyOut]


class VedOverride(BaseModel):
    country_iso2: str = Field(min_length=2, max_length=2)
    direction: Literal["import", "export", "unknown"]


class OverridesUpdate(BaseModel):
    industry_id: str | None = None
    ved: list[VedOverride] | None = Field(default=None, max_length=30)
    products: dict[str, bool] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    reset: list[OverrideFieldName] = Field(default_factory=list)


# ── лента (§4.3) ──
class FeedItem(BaseModel):
    event_id: int
    status: Literal["ready", "pending", "generating", "failed"]
    insight_id: str | None
    run_id: str | None
    headline: str
    why_you: str | None
    chain_preview: str | None
    direction: Direction
    impact_level: ImpactLevel
    score: float
    confidence_level: Level | None
    event_title: str
    event_type: str
    published_at: datetime
    publishers: list[str]
    source_count: int
    stale: bool
    needs_review: bool


class FeedResponse(BaseModel):
    items: list[FeedItem]
    next_cursor: str | None
    total: int
    generated_at: datetime
    budget_mode: BudgetMode


# ── инсайты, трасса, обратная связь (§4.4) ──
FeedbackReason = Literal[
    "not_relevant",
    "already_known",
    "wrong_facts",
    "too_generic",
    "unclear",
    "useful_action",
    "useful_risk",
    "other",
]


class FeedbackIn(BaseModel):
    useful: bool
    reason: FeedbackReason | None = None
    comment: str | None = Field(default=None, max_length=500)


class FeedbackOut(FeedbackIn):
    created_at: datetime


class InsightDetailResponse(BaseModel):
    insight: Insight
    my_feedback: FeedbackOut | None
    stale: bool


class RunInfo(BaseModel):
    id: str
    kind: str
    mode: str
    status: str
    event_id: int | None
    insight_id: str | None
    message_id: int | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    cost_rub: float


class TraceEventOut(BaseModel):
    seq: int
    ts: datetime
    type: str
    phase: str
    title: str
    status: Literal["ok", "warn", "error", "info"]
    payload: dict[str, Any]
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_rub: float | None
    latency_ms: int | None


class TraceResponse(BaseModel):
    run: RunInfo
    events: list[TraceEventOut]


# ── источники, телеметрия, заявки (§4.7) ──
class SourceDetail(BaseModel):
    id: str
    kind: SourceKind
    title: str
    publisher: str | None
    url: str | None
    published_at: datetime | None
    excerpt: str
    text: str | None
    doc_title: str | None
    page: int | None
    data: dict[str, Any] | None


UiEventType = Literal[
    "feed_view",
    "insight_open",
    "source_open",
    "trace_open",
    "chat_open",
    "brief_view",
    "analyze_submit",
    "product_open",
]


class UiEventIn(BaseModel):
    type: UiEventType
    insight_id: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class LeadIn(BaseModel):
    product_id: str = Field(max_length=64)
    insight_id: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=500)
    confirm: Literal[True]


class LeadOut(BaseModel):
    id: int
    product_name: str
    message: str


# ── генерация, фича B, чат (§4.4–4.6) ──
class GenerateResponse(BaseModel):
    status: Literal["ready", "started", "running"]
    insight_id: str | None
    run_id: str | None


class RunRef(BaseModel):
    run_id: str


class AnalyzeHistoryItem(BaseModel):
    run_id: str
    created_at: datetime
    status: str
    input_label: str
    insight_id: str | None
    headline: str | None


class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    thread_id: str | None = Field(default=None, max_length=64)


class ChatStartResponse(BaseModel):
    run_id: str
    thread_id: str
    user_message_id: int


class ChatMessageOut(BaseModel):
    id: int
    role: Literal["user", "assistant"]
    text: str | None
    answer: ChatAnswer | None
    sources: list[SourceRef]
    created_at: datetime


class ChatThreadResponse(BaseModel):
    thread_id: str | None
    messages: list[ChatMessageOut]
