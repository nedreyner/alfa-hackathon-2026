"""Схема инсайта: черновик модели, опубликованный инсайт, отчёт проверки (docs/08-agent.md §8, §9)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.ranking.models import ChainGraph, Direction, ImpactLevel, Role

ClaimType = Literal["fact", "bank", "ai"]
Level = Literal["low", "medium", "high"]
Horizon = Literal["days", "weeks", "months", "quarters"]
Urgency = Literal["now", "this_week", "this_month", "monitor"]
SourceKind = Literal["news", "alfa", "cbr", "client_data", "user_input"]
InsightStatus = Literal["published", "needs_review", "rejected"]


class Claim(BaseModel):
    text: str = Field(min_length=8, max_length=400, description="Одно предложение")
    type: ClaimType
    refs: list[str] = Field(
        default_factory=list,
        max_length=6,
        description="В черновике — идентификаторы evidence (E1, E2…); в опубликованном инсайте — id источников",
    )
    confidence: Level | None = Field(default=None, description="Обязательно для type=ai")


class WhatHappened(BaseModel):
    facts: list[Claim] = Field(min_length=1, max_length=4)
    assumptions: list[Claim] = Field(default_factory=list, max_length=3)


class WhyItMatters(BaseModel):
    summary: Claim
    client_features_used: list[str] = Field(min_length=1, max_length=8)
    chain_ids: list[str] = Field(default_factory=list, max_length=6)


class Consequence(BaseModel):
    kind: Literal["risk", "opportunity"]
    title: str = Field(max_length=80)
    claim: Claim
    probability: Level
    impact: Level
    horizon: Horizon


class Action(BaseModel):
    title: str = Field(max_length=90)
    claim: Claim
    owner_role: Role
    urgency: Urgency
    product_id: str | None = None


class BankView(BaseModel):
    available: bool
    claims: list[Claim] = Field(default_factory=list, max_length=3)
    alignment: Literal["supports", "neutral", "contradicts", "no_data"]


class InsightDraft(BaseModel):
    """Персональный разбор события для компании-клиента."""

    headline: str = Field(max_length=110)
    why_you: str = Field(max_length=140)
    direction: Direction
    impact_level: ImpactLevel
    what_happened: WhatHappened
    why_it_matters: WhyItMatters
    consequences: list[Consequence] = Field(min_length=1, max_length=4)
    actions: list[Action] = Field(min_length=1, max_length=4)
    bank_view: BankView

    def claims(self) -> list[tuple[str, Claim]]:
        """Все утверждения с путями (`what_happened.facts[0]`, …) — для проверки и деградации."""
        out: list[tuple[str, Claim]] = []
        out += [(f"what_happened.facts[{i}]", c) for i, c in enumerate(self.what_happened.facts)]
        out += [(f"what_happened.assumptions[{i}]", c) for i, c in enumerate(self.what_happened.assumptions)]
        out.append(("why_it_matters.summary", self.why_it_matters.summary))
        out += [(f"consequences[{i}].claim", c.claim) for i, c in enumerate(self.consequences)]
        out += [(f"actions[{i}].claim", a.claim) for i, a in enumerate(self.actions)]
        out += [(f"bank_view.claims[{i}]", c) for i, c in enumerate(self.bank_view.claims)]
        return out


# ── опубликованный инсайт ──
class SourceRef(BaseModel):
    id: str
    kind: SourceKind
    title: str
    publisher: str | None = None
    url: str | None = None
    published_at: datetime | None = None


class ProductOffer(BaseModel):
    product_id: str
    name: str
    pitch: str
    url: str | None = None
    action_index: int


class ConfidenceInfo(BaseModel):
    value: float
    level: Level
    reasons: list[str]


class VerificationSummary(BaseModel):
    passed: bool
    supported_share: float
    attempts: int
    removed_claims: int
    warnings: list[str]
    llm_skipped: bool


class EventBrief(BaseModel):
    id: int
    title: str
    summary: str
    event_type: str
    importance: int
    first_seen_at: datetime
    last_seen_at: datetime
    publishers: list[str]
    news_count: int
    visibility: Literal["public", "private"]
    injection_suspected: bool


class Insight(InsightDraft):
    id: str
    company_id: str
    status: InsightStatus
    event: EventBrief
    chain: ChainGraph
    chain_preview: str | None
    sources: list[SourceRef]
    products: list[ProductOffer]
    confidence: ConfidenceInfo
    verification: VerificationSummary
    role_generated_for: Role
    prompt_version: str
    profile_version: str
    model: str
    trace_id: str
    cost_rub: float
    created_at: datetime


# ── проверка ──
class ClaimVerdict(BaseModel):
    path: str
    verdict: Literal["supported", "partial", "unsupported", "contradicted"]
    comment: str = Field(default="", max_length=200)


class VerifyLLMOutput(BaseModel):
    """Вердикты по утверждениям инсайта."""

    verdicts: list[ClaimVerdict]
    contradictions: list[str] = Field(default_factory=list, max_length=5)
    missing: list[str] = Field(default_factory=list, max_length=4)


class CheckResult(BaseModel):
    code: str
    status: Literal["pass", "warn", "fail"]
    message: str
    paths: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    passed: bool
    attempt: int
    checks: list[CheckResult]
    verdicts: list[ClaimVerdict]
    contradictions: list[str]
    missing: list[str]
    supported_share: float
    issues: list[str]
    llm_skipped: bool
