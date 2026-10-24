"""Итоговый скор события для компании и роли (docs/07-ranking.md §6, §8)."""

from __future__ import annotations

from datetime import datetime

from alfa_insight.data.models import CompanyProfile
from alfa_insight.ranking.models import (
    EventSignal,
    Exposure,
    ImpactLevel,
    RankComponents,
    RankingConfig,
    Role,
)


def score_exposure(
    exposure: Exposure,
    event: EventSignal,
    profile: CompanyProfile,
    role: Role,
    cfg: RankingConfig,
    now: datetime,
) -> RankComponents:
    r = exposure.relevance
    imp = cfg.importance.base + cfg.importance.slope * event.importance / 5
    age_h = max(0.0, (now - event.last_seen_at).total_seconds() / 3600)
    phi = 0.5 ** (age_h / cfg.roles[role].half_life_h)
    f = cfg.freshness.floor + (1 - cfg.freshness.floor) * phi
    t = event.max_trust * (
        1 + cfg.trust.publisher_bonus * min(max(event.publisher_count - 1, 0), cfg.trust.publisher_bonus_cap)
    )
    region = profile.region_code
    g = cfg.region_bonus if region and region.startswith("RU-") and region in event.geo else 0.0
    score = r * imp * f * t * (1 + g)
    return RankComponents(
        relevance=round(r, 6),
        importance_factor=round(imp, 6),
        freshness=round(phi, 6),
        freshness_factor=round(f, 6),
        trust_factor=round(t, 6),
        region_bonus=g,
        score=round(score, 6),
    )


def impact_level(score: float, importance: int, cfg: RankingConfig) -> ImpactLevel:
    levels = cfg.impact_levels
    crit = levels["critical"]
    if score >= crit.min_score and importance >= (crit.min_importance or 0):
        return "critical"
    if score >= levels["high"].min_score:
        return "high"
    if score >= levels["medium"].min_score:
        return "medium"
    return "low"
