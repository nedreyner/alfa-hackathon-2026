"""Контекст и лимиты прогона агента (docs/08-agent.md §3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alfa_insight.agent.evidence import EvidenceRegistry
from alfa_insight.agent.trace import TraceWriter
from alfa_insight.appctx import AppContext
from alfa_insight.data.models import CompanyProfile
from alfa_insight.llm.types import Priority
from alfa_insight.ranking.models import Role
from alfa_insight.timeutil import utc_now

RunKind = Literal["insight", "analyze", "chat"]
RunMode = Literal["pipeline", "agentic"]


class AgentLimits(BaseModel):
    max_tool_rounds: int = 3
    max_tool_calls: int = 8
    max_revisions: int = 1
    max_evidence: int = 30
    max_cost_rub: float = 5.0
    timeout_s: int = 60
    evidence_text_chars: int = 1500

    @classmethod
    def from_app(cls, app: AppContext) -> AgentLimits:
        return cls(max_cost_rub=app.settings.llm_max_run_cost_rub)


@dataclass
class AgentContext:
    app: AppContext
    run_id: str
    kind: RunKind
    mode: RunMode
    company_id: str
    role: Role
    profile: CompanyProfile
    event_id: int | None
    priority: Priority
    limits: AgentLimits
    evidence: EvidenceRegistry
    trace: TraceWriter
    allowed_event_ids: set[int] = field(default_factory=set)
    started_at: datetime = field(default_factory=utc_now)
    cost_rub: float = 0.0
    tool_calls: int = 0

    @classmethod
    def create(
        cls,
        app: AppContext,
        *,
        run_id: str,
        kind: RunKind,
        mode: RunMode,
        profile: CompanyProfile,
        role: Role,
        event_id: int | None,
        priority: Priority = "interactive",
        limits: AgentLimits | None = None,
    ) -> AgentContext:
        lim = limits or AgentLimits.from_app(app)
        return cls(
            app=app,
            run_id=run_id,
            kind=kind,
            mode=mode,
            company_id=profile.company_id,
            role=role,
            profile=profile,
            event_id=event_id,
            priority=priority,
            limits=lim,
            evidence=EvidenceRegistry(text_chars=lim.evidence_text_chars, max_items=lim.max_evidence),
            trace=TraceWriter(app.db, run_id),
            allowed_event_ids={event_id} if event_id is not None else set(),
        )

    @property
    def elapsed_s(self) -> float:
        return (utc_now() - self.started_at).total_seconds()

    @property
    def timed_out(self) -> bool:
        return self.elapsed_s > self.limits.timeout_s
