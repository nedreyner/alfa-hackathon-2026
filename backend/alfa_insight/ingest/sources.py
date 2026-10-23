"""Конфиг источников `config/sources.yaml` (docs/06-ingestion-search.md §2)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.config_models import load_yaml

USER_TRUST = 0.5


class SourceDefaults(BaseModel):
    timeout_s: float = 15.0
    max_items: int = 100
    full_text: bool = True
    enabled: bool = True
    geo: Literal["any", "ru"] = "any"


class Source(BaseModel):
    id: str
    as_source: str | None = None  # под каким source_id писать новости (доп. ленты того же издания)
    publisher: str
    url: str
    trust: float = Field(ge=0, le=1)
    kind: Literal["official", "agency", "media", "other"] = "media"
    categories_allow: list[str] | None = None
    categories_allow_prefix: list[str] | None = None
    categories_soft: bool = False
    timeout_s: float | None = None
    max_items: int | None = None
    full_text: bool | None = None
    enabled: bool | None = None
    geo: Literal["any", "ru"] | None = None

    @property
    def news_source_id(self) -> str:
        return self.as_source or self.id

    @property
    def has_category_filter(self) -> bool:
        return bool(self.categories_allow or self.categories_allow_prefix)

    def category_allowed(self, categories: list[str]) -> bool:
        if not self.has_category_filter:
            return True
        for cat in categories:
            if self.categories_allow and cat in self.categories_allow:
                return True
            if self.categories_allow_prefix and any(cat.startswith(p) for p in self.categories_allow_prefix):
                return True
        return False


class SourcesConfig(BaseModel):
    version: int = 1
    user_agent: str = "AlfaInsightBot/0.1"
    defaults: SourceDefaults = Field(default_factory=SourceDefaults)
    sources: list[Source]

    def model_post_init(self, __context: object) -> None:
        d = self.defaults
        for s in self.sources:
            s.timeout_s = s.timeout_s if s.timeout_s is not None else d.timeout_s
            s.max_items = s.max_items if s.max_items is not None else d.max_items
            s.full_text = s.full_text if s.full_text is not None else d.full_text
            s.enabled = s.enabled if s.enabled is not None else d.enabled
            s.geo = s.geo or d.geo

    def get(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.id == source_id), None)

    def active(self, ingest_geo: str) -> list[Source]:
        return [s for s in self.sources if s.enabled and (s.geo != "ru" or ingest_geo == "ru")]

    def trust(self, source_id: str) -> float:
        src = self.get(source_id)
        return src.trust if src else USER_TRUST


def load_sources(config_dir: Path) -> SourcesConfig:
    return load_yaml(config_dir / "sources.yaml", SourcesConfig)
