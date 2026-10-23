"""Крупнейшие контрагенты компании из `top_counterparties` (названия ИП уже замаскированы при сборке)."""

from __future__ import annotations

from typing import Literal

from alfa_insight.data.models import Counterparty, FlowDirection
from alfa_insight.data.profiles import IP_LABEL, is_individual
from alfa_insight.db.duck import DuckReader
from alfa_insight.reference.taxonomy import Taxonomy

DirectionArg = FlowDirection | Literal["suppliers", "buyers"]
_ALIASES = {"suppliers": "out", "buyers": "in", "out": "out", "in": "in"}
UNNAMED = "Контрагент вне базы"


class CounterpartyReader:
    def __init__(self, duck: DuckReader, taxonomy: Taxonomy):
        self.duck = duck
        self.taxonomy = taxonomy

    def top(
        self,
        company_id: str,
        direction: DirectionArg,
        industry_id: str | None = None,
        limit: int = 10,
    ) -> list[Counterparty]:
        d = _ALIASES[direction]
        sql = (
            "SELECT counterparty_id, name, inn, industry_id, share, rank FROM top_counterparties "
            "WHERE company_id = ? AND direction = ?"
        )
        params: list[object] = [company_id, d]
        if industry_id:
            sql += " AND industry_id = ?"
            params.append(industry_id)
        sql += " ORDER BY rank LIMIT ?"
        params.append(int(limit))
        items = []
        for r in self.duck.rows(sql, params):
            name = r["name"] or UNNAMED
            if is_individual(r.get("inn"), name):
                name = IP_LABEL
            ind = self.taxonomy.industries.get(r["industry_id"])
            items.append(
                Counterparty(
                    counterparty_id=r["counterparty_id"],
                    name=name,
                    industry_id=r["industry_id"],
                    industry_name=ind.name if ind else r["industry_id"],
                    direction=d,  # type: ignore[arg-type]
                    share=float(r["share"] or 0.0),
                    rank=int(r["rank"]),
                )
            )
        return items
