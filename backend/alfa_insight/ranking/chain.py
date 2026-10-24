"""Пути влияния события на компанию — «цепная реакция» (docs/07-ranking.md §4, §5, §9.1, §11)."""

from __future__ import annotations

from typing import Literal

from alfa_insight.data.counterparties import CounterpartyReader
from alfa_insight.data.models import CompanyProfile
from alfa_insight.ranking.effects import DIRECTION_RU, EFFECT_SHORT, cell, combine, factor_direction
from alfa_insight.ranking.models import (
    Basis,
    ChainEdge,
    ChainGraph,
    ChainNode,
    ChainPath,
    Channel,
    CounterpartyBrief,
    EventSignal,
    Exposure,
    RankingConfig,
    Role,
)
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.text.normalize import lower_name

MIN_PATH = 0.01
FULL_COVERAGE = 0.95
PREVIEW_EVENT_CHARS = 60


class BlendedShare:
    __slots__ = ("basis", "coverage", "raw_share", "value")

    def __init__(self, value: float, raw_share: float | None, basis: Basis, coverage: float):
        self.value, self.raw_share, self.basis, self.coverage = value, raw_share, basis, coverage


def blended_shares(
    profile: CompanyProfile, tax: Taxonomy, side: Literal["supply", "demand"]
) -> dict[str, BlendedShare]:
    """Ŝ(i) = κ·S(i) + (1 − κ)·S0(i) (§5). При direction_unknown покупатели — только типовые доли."""
    if side == "supply":
        mix, prior, kappa = (
            profile.suppliers_mix,
            tax.typical_suppliers(profile.industry_id),
            profile.coverage.get("supply", 0.0),
        )
    else:
        mix, prior, kappa = (
            profile.buyers_mix,
            tax.typical_buyers(profile.industry_id),
            profile.coverage.get("demand", 0.0),
        )
        if profile.direction_unknown:
            mix, kappa = [], 0.0
    if kappa <= 0 or not mix:
        kappa = 0.0
        basis: Basis = "prior"
    elif kappa >= FULL_COVERAGE:
        basis = "payments"
    else:
        basis = "blended"
    actual = {s.industry_id: s for s in mix}
    out: dict[str, BlendedShare] = {}
    for iid in set(actual) | set(prior):
        s = actual[iid].share if iid in actual else 0.0
        value = kappa * s + (1 - kappa) * prior.get(iid, 0.0)
        raw = actual[iid].share_total if iid in actual else None
        out[iid] = BlendedShare(value, raw, basis, kappa)
    return out


def compute_exposure(
    event: EventSignal,
    profile: CompanyProfile,
    role: Role,
    cfg: RankingConfig,
    tax: Taxonomy,
    counterparties: CounterpartyReader | None = None,
    shares: dict[str, dict[str, BlendedShare]] | None = None,
) -> Exposure:
    """`shares` — заранее посчитанные `blended_shares` профиля (пакетное ранжирование)."""
    paths: list[ChainPath] = []
    cap = cfg.max_path_contribution
    feature_keys = profile.feature_keys()

    def add(**kw: object) -> None:
        contribution = min(cap, float(kw.pop("raw_contribution")))  # type: ignore[arg-type]
        if contribution >= MIN_PATH:
            paths.append(ChainPath(id="", contribution=round(contribution, 6), **kw))  # type: ignore[arg-type]

    # own: основная и дополнительные отрасли
    own_targets = [(profile.industry_id, 1.0, "main_industry", "industry.main")]
    own_targets += [
        (sec, cfg.secondary_industry_weight, "secondary_industry", f"industry.secondary.{sec}")
        for sec in profile.secondary_industry_ids
    ]
    for tag in event.industries:
        s = tag.impact * tag.confidence
        for iid, w, basis, fkey in own_targets:
            if tag.industry_id != iid:
                continue
            m = cell(tax, "own", tag.effect)
            rw = cfg.role_channel(role, "own")
            add(
                channel="own", industry_id=iid, industry_name=tax.industry(iid).name, effect=tag.effect,
                company_weight=w, basis=basis, event_strength=round(s, 6), matrix_strength=m.strength,
                role_weight=rw, direction=m.direction, mechanism=m.mechanism,
                feature_keys=[fkey] if fkey in feature_keys else [],
                raw_contribution=cfg.channel_weights["own"] * rw * w * s * m.strength,
            )  # fmt: skip

    # supply / demand: отрасли-контрагенты
    for side, direction_db, fprefix in (("supply", "out", "suppliers"), ("demand", "in", "buyers")):
        side_shares = shares[side] if shares is not None else blended_shares(profile, tax, side)  # type: ignore[arg-type]
        for tag in event.industries:
            share = side_shares.get(tag.industry_id)
            if share is None or share.value < cfg.min_share:
                continue
            s = tag.impact * tag.confidence
            m = cell(tax, side, tag.effect)
            rw = cfg.role_channel(role, side)  # type: ignore[arg-type]
            tops: list[CounterpartyBrief] = []
            if counterparties is not None:
                tops = [
                    CounterpartyBrief(name=c.name, share=round(c.share, 6))
                    for c in counterparties.top(
                        profile.company_id,
                        "out" if direction_db == "out" else "in",
                        industry_id=tag.industry_id,
                        limit=3,
                    )
                ]
            fkey = f"{fprefix}.{tag.industry_id}"
            add(
                channel=side, industry_id=tag.industry_id, industry_name=tax.industry(tag.industry_id).name,
                effect=tag.effect, company_weight=round(share.value, 6), raw_share=share.raw_share,
                basis=share.basis, coverage=round(share.coverage, 6), event_strength=round(s, 6),
                matrix_strength=m.strength, role_weight=rw, direction=m.direction, mechanism=m.mechanism,
                top_counterparties=tops, feature_keys=[fkey] if fkey in feature_keys else [],
                raw_contribution=cfg.channel_weights[side] * rw * share.value * s * m.strength,  # type: ignore[index]
            )  # fmt: skip

    # factor: макрофакторы с экспозицией компании
    for ftag in event.factors:
        exp = profile.factor(ftag.factor_id)
        if exp is None or exp.exposure < cfg.min_factor_exposure:
            continue
        s = ftag.impact * ftag.confidence
        rw = cfg.role_channel(role, "factor") * cfg.role_factor(role, ftag.factor_id)
        direction = factor_direction(ftag.direction, exp.sign)
        factor = tax.factor(ftag.factor_id)
        mechanism = factor.opportunity_text if direction == "opportunity" else factor.risk_text
        fkey = f"factor.{ftag.factor_id}"
        add(
            channel="factor", factor_id=ftag.factor_id, factor_name=factor.name, factor_direction=ftag.direction,
            company_weight=exp.exposure, basis="profile_factor", event_strength=round(s, 6), matrix_strength=1.0,
            role_weight=round(rw, 6), direction=direction, mechanism=mechanism, reasons=list(exp.reasons),
            feature_keys=[fkey] if fkey in feature_keys else [],
            raw_contribution=cfg.channel_weights["factor"] * rw * exp.exposure * s,
        )  # fmt: skip

    paths.sort(key=lambda p: (-p.contribution, p.channel, p.industry_id or p.factor_id or ""))
    for i, p in enumerate(paths, 1):
        p.id = f"P{i}"
    relevance = 1.0
    for p in paths:
        relevance *= 1 - p.contribution
    totals: dict[Channel, float] = {"own": 0.0, "supply": 0.0, "demand": 0.0, "factor": 0.0}
    for p in paths:
        totals[p.channel] = round(totals[p.channel] + p.contribution, 6)
    return Exposure(
        event_id=event.event_id,
        company_id=profile.company_id,
        role=role,
        paths=paths,
        relevance=round(1 - relevance, 6) if paths else 0.0,
        direction=combine(((p.contribution, p.direction) for p in paths), cfg.direction_mixed_ratio),
        channel_totals=totals,
    )


def _trim(text: str, limit: int = PREVIEW_EVENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.:;—- ") + "…"


def pct(value: float) -> str:
    return f"{round(value * 100)}%"


def path_link(path: ChainPath, tax: Taxonomy) -> str:
    name = lower_name(path.industry_name)
    if path.channel in ("supply", "demand"):
        what = "закупок" if path.channel == "supply" else "продаж"
        if path.basis == "prior" or path.raw_share is None:
            return f"типично для отрасли ≈ {pct(path.company_weight)} {what} — {name}"
        return f"{pct(path.raw_share)} ваших {what} — {name}"
    if path.channel == "own":
        return f"ваша отрасль — {name}"
    reason = path.reasons[0] if path.reasons else "экспозиция компании"
    return f"{lower_name(path.factor_name)}: {reason}"


def chain_preview(event_title: str, exposure: Exposure, tax: Taxonomy) -> str | None:
    """«{событие} → {звено} → {риск|возможность}: {механизм}» по первому пути (§9.1)."""
    if not exposure.paths:
        return None
    p = exposure.paths[0]
    return f"{_trim(event_title)} → {path_link(p, tax)} → {DIRECTION_RU[p.direction]}: {p.mechanism}"


def build_graph(
    event_title: str, exposure: Exposure, tax: Taxonomy, *, path_sources: dict[str, list[str]] | None = None
) -> ChainGraph:
    """Колоночный граф по трём первым путям: событие → отрасль/фактор → экспозиция → последствие (§11)."""
    nodes: list[ChainNode] = [ChainNode(id="event", kind="event", label=_trim(event_title, 80), x=0, y=0)]
    edges: list[ChainEdge] = []
    sources = path_sources or {}
    for row, p in enumerate(exposure.paths[:3]):
        y = row * 110
        weight = round(p.contribution, 4)
        if p.channel == "factor":
            arrow = "рост" if (p.factor_direction or 1) > 0 else "снижение"
            mid = ChainNode(id=f"{p.id}-driver", kind="factor", label=f"{p.factor_name}: {arrow}", x=280, y=y)
        else:
            mid = ChainNode(
                id=f"{p.id}-driver",
                kind="industry",
                label=f"{p.industry_name}: {EFFECT_SHORT.get(p.effect or '', p.effect or '')}",
                x=280,
                y=y,
            )
        exposure_label = path_link(p, tax)
        exp_node = ChainNode(
            id=f"{p.id}-exposure", kind="exposure", label=exposure_label[:1].upper() + exposure_label[1:],
            sublabel=f"вклад {p.contribution:.2f}", x=560, y=y, source_ids=sources.get(p.id, []),
        )  # fmt: skip
        cons = ChainNode(
            id=f"{p.id}-consequence", kind="consequence", label=p.mechanism[:1].upper() + p.mechanism[1:],
            sublabel=DIRECTION_RU[p.direction], direction=p.direction, x=840, y=y,
        )  # fmt: skip
        nodes += [mid, exp_node, cons]
        edges += [
            ChainEdge(id=f"{p.id}-e1", source="event", target=mid.id, weight=weight),
            ChainEdge(id=f"{p.id}-e2", source=mid.id, target=exp_node.id, weight=weight),
            ChainEdge(id=f"{p.id}-e3", source=exp_node.id, target=cons.id, label=p.id, weight=weight),
        ]
    return ChainGraph(nodes=nodes, edges=edges)
