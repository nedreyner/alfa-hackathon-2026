"""DTO API (docs/09-api.md §4). Переиспользуют доменные модели, без копий."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from alfa_insight.data.models import CompanyProfile, IndustryShare
from alfa_insight.llm.budget import BudgetMode
from alfa_insight.ranking.models import Role


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
