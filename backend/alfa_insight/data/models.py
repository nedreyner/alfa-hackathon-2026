"""Модели профиля компании (docs/03-data.md §7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FlowDirection = Literal["out", "in"]  # out = поставщики, in = покупатели
RevenueBucket = Literal["15-30", "30-100", "100-500", "500+", "unknown"]


class IndustryShare(BaseModel):
    industry_id: str
    name: str
    share: float  # доля среди известных отраслей, 0..1
    share_total: float  # доля от всего объёма, включая unknown
    n_counterparties: int


class FactorExposure(BaseModel):
    factor_id: str
    name: str
    exposure: float  # 0..1
    sign: Literal[-1, 1]
    reasons: list[str]


class ProductInfo(BaseModel):
    has: bool
    amount_rub: float | None = None


class VedEntry(BaseModel):
    country_iso2: str | None
    country_name: str
    direction: Literal["import", "export", "unknown"]
    currencies: list[str] = Field(default_factory=list)


class Feature(BaseModel):
    key: str
    label: str
    value: str
    source: Literal["data", "override", "prior"]


class CompanyProfile(BaseModel):
    company_id: str
    name: str
    inn: str | None
    okved: str | None
    industry_id: str
    industry_name: str
    secondary_industry_ids: list[str] = Field(default_factory=list)
    region_code: str | None
    region_name: str | None
    revenue_rub: float | None
    revenue_bucket: RevenueBucket
    is_client: bool
    group_id: str | None
    products: dict[str, ProductInfo]
    ved: list[VedEntry]
    suppliers_mix: list[IndustryShare]
    buyers_mix: list[IndustryShare]
    coverage: dict[Literal["supply", "demand"], float]
    direction_unknown: bool = False
    top_buyer_share: float | None = None
    factor_exposure: list[FactorExposure]
    features: list[Feature]
    notes: str | None = None
    profile_version: str
    data_profile: Literal["real", "synthetic"]

    def feature_keys(self) -> set[str]:
        return {f.key for f in self.features}

    def factor(self, factor_id: str) -> FactorExposure | None:
        return next((f for f in self.factor_exposure if f.factor_id == factor_id), None)


class CompanySummary(BaseModel):
    company_id: str
    name: str
    industry_id: str
    industry_name: str
    region_name: str | None
    revenue_bucket: RevenueBucket
    is_client: bool
    is_demo: bool = False


class Counterparty(BaseModel):
    counterparty_id: str
    name: str
    industry_id: str
    industry_name: str
    direction: FlowDirection
    share: float
    rank: int
