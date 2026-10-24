"""Конструкторы профилей и событий для golden-тестов ранжирования."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from alfa_insight.config_models import load_yaml
from alfa_insight.data.models import CompanyProfile, FactorExposure, Feature, IndustryShare
from alfa_insight.ranking.models import EventSignal, FactorSignal, IndustrySignal, RankingConfig
from alfa_insight.reference.taxonomy import Taxonomy

ROOT = Path(__file__).resolve().parents[4]
TAX = Taxonomy(ROOT / "data" / "reference")
CFG = load_yaml(ROOT / "config" / "ranking.yaml", RankingConfig)
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def profile(
    company_id: str,
    industry_id: str,
    *,
    suppliers: dict[str, float] | None = None,  # industry → share_total
    buyers: dict[str, float] | None = None,
    coverage: tuple[float, float] = (0.0, 0.0),
    factors: dict[str, tuple[float, int, list[str]]] | None = None,
    region_code: str | None = None,
) -> CompanyProfile:
    def mix(shares: dict[str, float] | None, kappa: float) -> list[IndustryShare]:
        return [
            IndustryShare(
                industry_id=i,
                name=TAX.industry(i).name,
                share=(v / kappa if kappa else 0.0),
                share_total=v,
                n_counterparties=5,
            )
            for i, v in (shares or {}).items()
        ]

    fx = [
        FactorExposure(factor_id=f, name=TAX.factor(f).name, exposure=x, sign=sign, reasons=reasons)  # type: ignore[arg-type]
        for f, (x, sign, reasons) in (factors or {}).items()
    ]
    feats = [Feature(key="industry.main", label="Отрасль", value=industry_id, source="data")]
    feats += [Feature(key=f"suppliers.{i}", label="", value="", source="data") for i in (suppliers or {})]
    feats += [Feature(key=f"buyers.{i}", label="", value="", source="data") for i in (buyers or {})]
    feats += [Feature(key=f"factor.{f.factor_id}", label="", value="", source="data") for f in fx]
    return CompanyProfile(
        company_id=company_id, name=company_id, inn=None, okved=None, industry_id=industry_id,
        industry_name=TAX.industry(industry_id).name, region_code=region_code, region_name=None, revenue_rub=3e10,
        revenue_bucket="30-100", is_client=True, group_id=None, products={}, ved=[],
        suppliers_mix=mix(suppliers, coverage[0]), buyers_mix=mix(buyers, coverage[1]),
        coverage={"supply": coverage[0], "demand": coverage[1]}, factor_exposure=fx, features=feats,
        profile_version="test", data_profile="synthetic",
    )  # fmt: skip


def event(
    event_id: int = 1,
    *,
    title: str = "Событие",
    industries: list[tuple[str, str, float, float]] | None = None,
    factors: list[tuple[str, int, float, float]] | None = None,
    importance: int = 4,
    age_h: float = 6,
    publishers: int = 2,
    trust: float = 0.9,
    geo: list[str] | None = None,
) -> EventSignal:
    last = NOW - timedelta(hours=age_h)
    return EventSignal(
        event_id=event_id, title=title, event_type="other", importance=importance, horizon="weeks",
        first_seen_at=last, last_seen_at=last, publisher_count=publishers, max_trust=trust, tag_confidence=0.7,
        geo=geo or ["RU"],
        industries=[IndustrySignal(industry_id=i, effect=e, impact=imp, confidence=c) for i, e, imp, c in industries or []],
        factors=[FactorSignal(factor_id=f, direction=d, impact=imp, confidence=c) for f, d, imp, c in factors or []],  # type: ignore[arg-type]
    )  # fmt: skip


def example_12() -> tuple[CompanyProfile, EventSignal]:
    """Пример docs/07-ranking.md §12: SYN-DEMO-02 и «металлурги поднимают цены на арматуру»."""
    p = profile(
        "SYN-DEMO-02",
        "construction_buildings",
        suppliers={"metallurgy": 0.34},
        coverage=(0.90, 0.90),
        factors={"inflation": (0.2, -1, ["общий фактор"])},
    )
    e = event(
        title="Металлурги поднимают цены на арматуру на 8% с ноября",
        industries=[
            ("metallurgy", "prices_up", 1.0, 1.0),
            ("construction_buildings", "costs_up", 0.33, 0.67),
        ],
        factors=[("inflation", 1, 0.33, 0.33)],
    )
    return p, e
