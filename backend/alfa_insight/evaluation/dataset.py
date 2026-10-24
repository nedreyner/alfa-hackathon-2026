"""Офлайн-набор: пул кандидатов, разметка `eval/labels.csv`, скоринг вариантов (docs/12-quality.md §2–3)."""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from alfa_insight.appctx import AppContext
from alfa_insight.ranking.service import RankingService
from alfa_insight.store.events import EventSignal

POOL_TOP = 6
POOL_RANDOM = 4
POOL_SEED = 20261025
LABEL_FIELDS = ["company_id", "seed_id", "relevance", "direction", "labeler", "notes"]
POOL_FIELDS = ["company_id", "seed_id", "origin", "title"]
Direction = Literal["risk", "opportunity", "mixed", "none"]
Variant = Literal["ours", "industry_only", "no_payments"]
VARIANTS: tuple[Variant, ...] = ("ours", "industry_only", "no_payments")


@dataclass
class Label:
    company_id: str
    seed_id: str
    relevance: int
    direction: Direction
    labeler: str
    notes: str = ""

    @property
    def human(self) -> bool:
        return self.labeler.startswith("human:")


def eval_dir(app: AppContext) -> Path:
    return app.settings.repo_root / "eval"


def seed_events(app: AppContext) -> dict[str, int]:
    """seed_id ведущей новости → id публичного события с хотя бы одним отраслевым или факторным тегом."""
    rows = app.db.query(
        "SELECT e.id AS event_id, n.external_id AS seed_id FROM events e JOIN news n ON n.id = e.lead_news_id "
        "WHERE n.origin = 'seed' AND e.visibility = 'public' AND ("
        "EXISTS (SELECT 1 FROM event_industries i WHERE i.event_id = e.id) OR "
        "EXISTS (SELECT 1 FROM event_factors f WHERE f.event_id = e.id))"
    )
    return {r["seed_id"]: int(r["event_id"]) for r in rows}


def eval_now(app: AppContext, event_ids: list[int]) -> datetime:
    """Фиксированный `now` = самая свежая дата seed-событий + 2 ч: оценка не зависит от дня запуска."""
    signals = app.ranking.events.load_signals(event_ids)
    return max(s.last_seen_at for s in signals) + timedelta(hours=2)


def _service(app: AppContext, variant: Variant) -> RankingService:
    cfg = app.ranking_config
    if variant == "industry_only":
        weights = {ch: (w if ch == "own" else 0.0) for ch, w in cfg.channel_weights.items()}
        cfg = cfg.model_copy(update={"channel_weights": weights})
    return RankingService(app.db, app.profiles, cfg, app.taxonomy)


def score_events(
    app: AppContext,
    company_id: str,
    signals: list[EventSignal],
    now: datetime,
    variant: Variant = "ours",
    channel_weights: dict[str, float] | None = None,
) -> dict[int, tuple[float, str]]:
    """event_id → (скор, направление) в роли компании по умолчанию."""
    svc = _service(app, variant)
    if channel_weights is not None:
        svc.cfg = svc.cfg.model_copy(update={"channel_weights": channel_weights})
    profile = app.profiles.get(company_id)
    if variant == "no_payments":
        profile = profile.model_copy(update={"coverage": {}})
    role = default_role(app, company_id)
    out: dict[int, tuple[float, str]] = {}
    for s in signals:
        res = svc.rank_one(s, profile, role, now)
        out[s.event_id] = (res.score, res.direction)
    return out


def default_role(app: AppContext, company_id: str) -> Literal["cfo", "treasurer", "owner"]:
    return next((c.default_role for c in app.demo.companies if c.company_id == company_id), "cfo")


def build_pool(app: AppContext, companies: list[str]) -> list[dict[str, str]]:
    """6 лучших по нашему скору + 4 случайных размеченных события на компанию (фиксированный seed)."""
    by_seed = seed_events(app)
    ids = list(by_seed.values())
    signals = app.ranking.events.load_signals(ids)
    titles = {s.event_id: s.title for s in signals}
    now = eval_now(app, ids)
    seed_of = {eid: sid for sid, eid in by_seed.items()}
    rows = []
    for cid in companies:
        scores = score_events(app, cid, signals, now)
        ranked = sorted(scores, key=lambda e: (-scores[e][0], e))
        top = ranked[:POOL_TOP]
        rng = random.Random(f"{POOL_SEED}:{cid}")
        rest = sorted(set(ranked) - set(top))
        extra = rng.sample(rest, min(POOL_RANDOM, len(rest)))
        for origin, group in (("top", top), ("random", extra)):
            rows += [
                {"company_id": cid, "seed_id": seed_of[e], "origin": origin, "title": titles[e]}
                for e in group
            ]
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def read_labels(path: Path) -> list[Label]:
    return [
        Label(
            r["company_id"],
            r["seed_id"],
            int(r["relevance"]),
            r["direction"],  # type: ignore[arg-type]
            r["labeler"],
            r.get("notes") or "",
        )  # type: ignore[arg-type]
        for r in read_csv(path)
    ]


def write_labels(path: Path, labels: list[Label]) -> None:
    rows = [
        {"company_id": x.company_id, "seed_id": x.seed_id, "relevance": str(x.relevance), "direction": x.direction,
         "labeler": x.labeler, "notes": x.notes}
        for x in sorted(labels, key=lambda x: (x.company_id, x.seed_id, x.labeler))
    ]  # fmt: skip
    write_csv(path, rows, LABEL_FIELDS)


@dataclass
class Gold:
    """Итоговая разметка: по паре компания–событие одна оценка; источник — люди или (до их разметки) LLM."""

    labels: dict[tuple[str, str], Label]
    source: Literal["human", "llm", "none"]
    kappa: float | None
    overlap: int


def gold_labels(labels: list[Label]) -> Gold:
    from alfa_insight.evaluation.metrics import weighted_kappa

    human = [x for x in labels if x.human]
    pool = human or [x for x in labels if x.labeler == "llm"]
    source: Literal["human", "llm", "none"] = "human" if human else "llm" if pool else "none"
    by_pair: dict[tuple[str, str], list[Label]] = defaultdict(list)
    for x in pool:
        by_pair[(x.company_id, x.seed_id)].append(x)
    gold = {}
    a: list[int] = []
    b: list[int] = []
    for pair, xs in by_pair.items():
        final = next((x for x in xs if x.labeler == "human:final"), xs[0])
        gold[pair] = final
        people = sorted({x.labeler for x in xs if x.labeler != "human:final"})
        if source == "human" and len(people) >= 2:
            first = {x.labeler: x.relevance for x in xs}
            a.append(first[people[0]])
            b.append(first[people[1]])
    return Gold(gold, source, weighted_kappa(a, b) if a else None, len(a))
