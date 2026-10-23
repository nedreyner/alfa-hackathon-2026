"""Pydantic-модели справочников `data/reference/*.yaml` (docs/03-data.md §5)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Channel = Literal["own", "supply", "demand"]
Direction = Literal["risk", "opportunity", "mixed"]
Level = Literal["low", "medium", "high"]

EFFECT_IDS = (
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
)
CHANNELS: tuple[Channel, ...] = ("own", "supply", "demand")


class Industry(BaseModel):
    id: str
    name: str
    okved_prefixes: list[str] = Field(default_factory=list)
    factor_sensitivity: dict[str, tuple[float, Literal[-1, 1]]] = Field(default_factory=dict)
    typical_suppliers: dict[str, float] = Field(default_factory=dict)
    typical_buyers: dict[str, float] = Field(default_factory=dict)
    keywords: list[str] = Field(default_factory=list)

    @field_validator("okved_prefixes")
    @classmethod
    def _prefixes_min_len(cls, v: list[str]) -> list[str]:
        for p in v:
            if len(p.replace(".", "")) < 2:
                raise ValueError(f"префикс ОКВЭД короче 2 знаков: {p!r}")
        return v


class IndustriesFile(BaseModel):
    version: int
    industries: list[Industry]


class Factor(BaseModel):
    id: str
    name: str
    up_means: str
    risk_text: str
    opportunity_text: str
    macro_indicator: str | None = None


class FactorsFile(BaseModel):
    version: int
    factors: list[Factor]


class Effect(BaseModel):
    id: str
    meaning: str


class MatrixCell(BaseModel):
    direction: Direction
    strength: float = Field(ge=0, le=1)
    mechanism: str


class EffectsFile(BaseModel):
    version: int
    effects: list[Effect]
    matrix: dict[Channel, dict[str, MatrixCell]]


class EventType(BaseModel):
    id: str
    name: str
    default_factors: list[str] = Field(default_factory=list)


class EventTypesFile(BaseModel):
    version: int
    event_types: list[EventType]


class Country(BaseModel):
    iso2: str = Field(min_length=2, max_length=2)
    names: list[str]
    currencies: list[str] = Field(default_factory=list)
    payment_friction: Level = "medium"
    sanctions_scrutiny: Level = "medium"


class CountriesFile(BaseModel):
    version: int
    countries: list[Country]


class PrefilterLexicon(BaseModel):
    version: int
    econ: list[str]
    negative: list[str]
    negative_exceptions: dict[str, list[str]] = Field(default_factory=dict)
    boilerplate: list[str] = Field(default_factory=list)


class InjectionPattern(BaseModel):
    id: str
    lang: Literal["ru", "en", "any"]
    regex: str


class InjectionPatternsFile(BaseModel):
    version: int
    patterns: list[InjectionPattern]
    max_invisible_chars: int = 5
