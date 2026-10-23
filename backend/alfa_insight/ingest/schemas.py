"""Схема ответа LLM при разметке новости (docs/06-ingestion-search.md §8.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Effect = Literal[
    "prices_up",
    "prices_down",
    "demand_up",
    "demand_down",
    "supply_down",
    "supply_up",
    "costs_up",
    "costs_down",
    "regulation_tighter",
    "support_measures",
]


class IndustryImpactTag(BaseModel):
    industry_id: str
    effect: Effect
    impact: Literal[1, 2, 3]
    confidence: Literal[1, 2, 3]
    rationale: str = Field(max_length=200)


class FactorImpactTag(BaseModel):
    factor_id: str
    direction: Literal["up", "down"]
    impact: Literal[1, 2, 3]
    confidence: Literal[1, 2, 3]
    rationale: str = Field(max_length=200)


class EntityTag(BaseModel):
    kind: Literal["company", "gov", "person", "country", "org"]
    name: str = Field(max_length=120)


class KeyNumber(BaseModel):
    value: str = Field(max_length=40)
    unit: str | None = Field(default=None, max_length=30)
    context: str = Field(max_length=120)


class NewsTagging(BaseModel):
    """Разметка новости по закрытым справочникам."""

    is_business_relevant: bool
    summary: str = Field(max_length=400)
    event_type: str
    importance: Literal[1, 2, 3, 4, 5]
    horizon: Literal["days", "weeks", "months", "quarters"]
    industries: list[IndustryImpactTag] = Field(default_factory=list, max_length=6)
    factors: list[FactorImpactTag] = Field(default_factory=list, max_length=5)
    geo: list[str] = Field(default_factory=list, max_length=8)
    entities: list[EntityTag] = Field(default_factory=list, max_length=8)
    key_numbers: list[KeyNumber] = Field(default_factory=list, max_length=6)
    injection_suspected: bool = False


SCALE = {1: 0.33, 2: 0.67, 3: 1.0}


class StoredIndustry(BaseModel):
    industry_id: str
    effect: str
    impact: float
    confidence: float
    rationale: str | None = None


class StoredFactor(BaseModel):
    factor_id: str
    direction: Literal[-1, 1]
    impact: float
    confidence: float
    rationale: str | None = None


class CleanTagging(BaseModel):
    """Разметка после постобработки: только известные id, шкалы 0..1, направление ±1."""

    is_business_relevant: bool
    summary: str
    event_type: str
    importance: int
    horizon: str
    industries: list[StoredIndustry]
    factors: list[StoredFactor]
    geo: list[str]
    entities: list[EntityTag]
    key_numbers: list[KeyNumber]
    injection_suspected: bool
    warnings: list[str] = Field(default_factory=list)
