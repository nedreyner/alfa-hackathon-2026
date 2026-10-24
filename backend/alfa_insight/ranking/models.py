"""Модели ранжирования и «цепной реакции» (docs/07-ranking.md §2, §4, §6, §9, §11)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.store.events import EventSignal, FactorSignal, IndustrySignal

__all__ = [
    "ChainEdge",
    "ChainGraph",
    "ChainNode",
    "ChainPath",
    "Channel",
    "CounterpartyBrief",
    "Direction",
    "EventSignal",
    "Exposure",
    "FactorSignal",
    "ImpactLevel",
    "IndustrySignal",
    "RankComponents",
    "RankResult",
    "RankingConfig",
    "Role",
]

Channel = Literal["own", "supply", "demand", "factor"]
Direction = Literal["risk", "opportunity", "mixed"]
ImpactLevel = Literal["low", "medium", "high", "critical"]
Role = Literal["cfo", "treasurer", "owner"]
ROLES: tuple[Role, ...] = ("cfo", "treasurer", "owner")
Basis = Literal["main_industry", "secondary_industry", "payments", "blended", "prior", "profile_factor"]


# ── config/ranking.yaml ──
class ImportanceCfg(BaseModel):
    base: float = 0.6
    slope: float = 0.4


class FreshnessCfg(BaseModel):
    floor: float = 0.5


class TrustCfg(BaseModel):
    publisher_bonus: float = 0.05
    publisher_bonus_cap: int = 4


class LevelCfg(BaseModel):
    min_score: float
    min_importance: int | None = None


class FeedCfg(BaseModel):
    min_score: float = 0.10
    min_relevance: float = 0.08
    page_size: int = 20


class RoleCfg(BaseModel):
    half_life_h: float
    channels: dict[Channel, float] = Field(default_factory=dict)
    factors: dict[str, float] = Field(default_factory=dict)


class RerankCfg(BaseModel):
    enabled: bool = False
    top_n: int = 20
    alpha: float = 0.4


class RankingConfig(BaseModel):
    version: int = 1
    window_days: int = 7
    min_relevance_to_store: float = 0.05
    channel_weights: dict[Channel, float]
    secondary_industry_weight: float = 0.5
    min_share: float = 0.02
    min_factor_exposure: float = 0.15
    max_path_contribution: float = 0.95
    direction_mixed_ratio: float = 0.25
    importance: ImportanceCfg = Field(default_factory=ImportanceCfg)
    freshness: FreshnessCfg = Field(default_factory=FreshnessCfg)
    trust: TrustCfg = Field(default_factory=TrustCfg)
    region_bonus: float = 0.10
    impact_levels: dict[Literal["critical", "high", "medium"], LevelCfg]
    feed: FeedCfg = Field(default_factory=FeedCfg)
    roles: dict[Role, RoleCfg]
    rerank: RerankCfg = Field(default_factory=RerankCfg)

    def role_channel(self, role: Role, channel: Channel) -> float:
        return self.roles[role].channels.get(channel, 1.0)

    def role_factor(self, role: Role, factor_id: str) -> float:
        return self.roles[role].factors.get(factor_id, 1.0)


# ── пути влияния ──
class CounterpartyBrief(BaseModel):
    name: str
    share: float


class ChainPath(BaseModel):
    id: str
    channel: Channel
    industry_id: str | None = None
    industry_name: str | None = None
    effect: str | None = None
    factor_id: str | None = None
    factor_name: str | None = None
    factor_direction: Literal[-1, 1] | None = None
    company_weight: float
    raw_share: float | None = None
    basis: Basis
    coverage: float | None = None
    event_strength: float
    matrix_strength: float
    role_weight: float
    contribution: float
    direction: Direction
    mechanism: str
    top_counterparties: list[CounterpartyBrief] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    feature_keys: list[str] = Field(default_factory=list)


class Exposure(BaseModel):
    event_id: int
    company_id: str
    role: Role
    paths: list[ChainPath]
    relevance: float
    direction: Direction
    channel_totals: dict[Channel, float]


class RankComponents(BaseModel):
    relevance: float
    importance_factor: float
    freshness: float
    freshness_factor: float
    trust_factor: float
    region_bonus: float
    score: float


class RankResult(BaseModel):
    exposure: Exposure
    components: RankComponents
    score: float
    direction: Direction
    impact_level: ImpactLevel
    chain_preview: str | None


# ── граф для интерфейса ──
class ChainNode(BaseModel):
    id: str
    kind: Literal["event", "industry", "factor", "exposure", "consequence"]
    label: str
    sublabel: str | None = None
    direction: Direction | None = None
    x: int
    y: int
    source_ids: list[str] = Field(default_factory=list)


class ChainEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str | None = None
    weight: float


class ChainGraph(BaseModel):
    nodes: list[ChainNode]
    edges: list[ChainEdge]
