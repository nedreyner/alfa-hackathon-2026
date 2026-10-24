"""Пакетное ранжирование событий для целевых компаний и трёх ролей (docs/07-ranking.md §9)."""

from __future__ import annotations

from datetime import datetime, timedelta

from alfa_insight.data.models import CompanyProfile
from alfa_insight.data.profiles import ProfileStore
from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.ranking.chain import chain_preview, compute_exposure
from alfa_insight.ranking.models import ROLES, EventSignal, RankingConfig, RankResult, Role
from alfa_insight.ranking.scorer import impact_level, score_exposure
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.store.events import EventStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.timeutil import to_iso, utc_now


class RankingService:
    def __init__(self, db: SqliteDB, profiles: ProfileStore, cfg: RankingConfig, taxonomy: Taxonomy):
        self.db = db
        self.profiles = profiles
        self.cfg = cfg
        self.tax = taxonomy
        self.events = EventStore(db)
        self.store = RankingStore(db)

    def rank_one(
        self, event: EventSignal, profile: CompanyProfile, role: Role, now: datetime | None = None
    ) -> RankResult:
        now = now or utc_now()
        exposure = compute_exposure(event, profile, role, self.cfg, self.tax)
        comp = score_exposure(exposure, event, profile, role, self.cfg, now)
        return RankResult(
            exposure=exposure,
            components=comp,
            score=comp.score,
            direction=exposure.direction,
            impact_level=impact_level(comp.score, event.importance, self.cfg),
            chain_preview=chain_preview(event.title, exposure, self.tax),
        )

    def _window_events(self, now: datetime) -> list[EventSignal]:
        since = to_iso(now - timedelta(days=self.cfg.window_days))
        return self.events.load_signals(self.events.list_ids(visibility="public", since=since))

    def _rank(self, events: list[EventSignal], profiles: list[CompanyProfile], now: datetime) -> int:
        rows = []
        drop = []
        for profile in profiles:
            for event in events:
                if event.visibility == "private" and event.owner_company_id != profile.company_id:
                    continue
                for role in ROLES:
                    res = self.rank_one(event, profile, role, now)
                    if res.exposure.relevance < self.cfg.min_relevance_to_store:
                        drop.append((profile.company_id, event.event_id, role))
                        continue
                    rows.append(
                        {
                            "company_id": profile.company_id,
                            "event_id": event.event_id,
                            "role": role,
                            "score": res.score,
                            "relevance": res.exposure.relevance,
                            "direction": res.direction,
                            "impact_level": res.impact_level,
                            "chain_preview": res.chain_preview,
                            "components_json": res.components.model_dump_json(),
                            "chain_json": res.exposure.model_dump_json(
                                exclude={"paths": {"__all__": {"top_counterparties"}}}
                            ),
                            "profile_version": profile.profile_version,
                        }
                    )
        self.store.replace(rows, drop=drop)
        return len(rows)

    def rank_company(self, company_id: str, *, now: datetime | None = None) -> int:
        now = now or utc_now()
        events = self._window_events(now)
        private_ids = [
            r["id"]
            for r in self.db.query(
                "SELECT id FROM events WHERE visibility = 'private' AND owner_company_id = ?", (company_id,)
            )
        ]
        events += self.events.load_signals(private_ids)
        self.store.delete_company(company_id, keep_event_ids={e.event_id for e in events})
        return self._rank(events, [self.profiles.get(company_id)], now)

    def rank_events(self, event_ids: list[int], *, now: datetime | None = None) -> int:
        now = now or utc_now()
        events = [e for e in self.events.load_signals(event_ids) if e.visibility == "public"]
        return self._rank(events, [self.profiles.get(c) for c in self.profiles.company_ids()], now)

    def rank_all(self, *, now: datetime | None = None) -> int:
        now = now or utc_now()
        events = self._window_events(now)
        profiles = [self.profiles.get(c) for c in self.profiles.company_ids()]
        keep = {e.event_id for e in events}
        for p in profiles:
            self.store.delete_company(p.company_id, keep_event_ids=keep)
        return self._rank(events, profiles, now)
