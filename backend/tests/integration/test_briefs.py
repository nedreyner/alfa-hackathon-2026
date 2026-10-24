from __future__ import annotations

import asyncio

from alfa_insight.agent.briefs import build_brief, pick_action
from alfa_insight.agent.schemas import Insight
from alfa_insight.services.jobs import JobRunner
from alfa_insight.store.insights import InsightStore
from alfa_insight.store.rankings import RankingStore
from alfa_insight.store.runs import RunStore

COMPANY = "SYN-DEMO-01"


def test_roles_differ_and_pending(seeded_ctx) -> None:  # type: ignore[no-untyped-def]
    app = seeded_ctx
    app.ranking.rank_company(COMPANY)
    briefs = {role: build_brief(app, COMPANY, role) for role in ("cfo", "treasurer", "owner")}
    orders = {role: [i.event_id for i in b.items] for role, b in briefs.items()}
    assert all(len(o) == 3 for o in orders.values())
    assert len({tuple(o) for o in orders.values()}) > 1, orders  # роли видят разный порядок
    assert all(i.status == "pending" and i.why_you for b in briefs.values() for i in b.items)
    assert all(b.reading_time_s >= 10 for b in briefs.values())

    # готовый инсайт поднимается вверх, остальные — pending
    role = "treasurer"
    third = RankingStore(app.db).top(COMPANY, role, limit=3)[2]
    runner = JobRunner(app)

    async def make() -> str:
        res = runner.start_interactive(COMPANY, role, third["event_id"])
        await runner.wait_all()
        return RunStore(app.db).get(res.run_id).insight_id  # type: ignore[union-attr,return-value]

    insight_id = asyncio.run(make())
    brief = build_brief(app, COMPANY, role)
    assert brief.items[0].status == "ready" and brief.items[0].insight_id == insight_id
    assert [i.status for i in brief.items].count("pending") == 2
    ins = Insight.model_validate(InsightStore(app.db).get(insight_id).payload)  # type: ignore[union-attr]
    assert brief.items[0].action is not None and brief.items[0].headline == ins.headline


def test_pick_action_by_role() -> None:
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "agent" / "insight_example.json").read_text()
    )
    ins = Insight.model_validate(raw)
    action, product = pick_action(ins, "treasurer")
    assert (
        action is not None
        and action.owner_role == "treasurer"
        and product is not None
        and product.action_index == 1
    )
    action, product = pick_action(ins, "owner")  # действия для собственника нет → первое
    assert action is ins.actions[0] and product is None


def test_distinct_themes() -> None:
    from alfa_insight.agent.briefs import distinct_themes

    items = ["rate1", "rate2", "duty", "rate3", "fx"]
    theme = lambda s: {s.rstrip("0123456789")}  # noqa: E731
    assert distinct_themes(items, theme, 3) == ["rate1", "duty", "fx"]
    assert distinct_themes(["rate1", "rate2", "duty"], theme, 3) == [
        "rate1",
        "duty",
        "rate2",
    ]  # добор по порядку
    # тема по любому из тегов: инфляция с главным путём через ставку не встаёт рядом с решением по ставке
    tags = {
        "rate": {"type:policy", "factor:key_rate"},
        "cpi": {"type:macro", "factor:key_rate"},
        "duty": {"type:tariff"},
    }
    assert distinct_themes(["rate", "cpi", "duty"], lambda s: tags[s], 2) == ["rate", "duty"]
