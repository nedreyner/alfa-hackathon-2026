"""Каталог продуктов банка и подбор кандидатов по путям влияния (docs/08-agent.md §15)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from alfa_insight.config_models import load_yaml
from alfa_insight.data.models import CompanyProfile
from alfa_insight.ranking.effects import DIRECTION_RU, EFFECT_SHORT
from alfa_insight.ranking.models import ChainPath, Channel, Direction, Exposure, Role
from alfa_insight.text.normalize import lower_name

MATCH_PATHS = 5
MAX_CANDIDATES = 3
ROLE_BOOST = 1.2
CHANNEL_WHEN = {"own": "ваша отрасль", "supply": "поставщики", "demand": "покупатели", "factor": "фактор"}


class Trigger(BaseModel):
    channel: Channel
    effect: str | None = None
    factor: str | None = None
    factor_prefix: str | None = None
    direction: Direction | None = None
    event_direction: Literal["up", "down"] | None = None

    def matches(self, path: ChainPath) -> bool:
        if path.channel != self.channel:
            return False
        if self.effect is not None and path.effect != self.effect:
            return False
        if self.factor is not None and path.factor_id != self.factor:
            return False
        if self.factor_prefix is not None and not (path.factor_id or "").startswith(self.factor_prefix):
            return False
        if self.direction is not None and path.direction != self.direction:
            return False
        if self.event_direction is not None:
            up = (path.factor_direction or 0) > 0
            if (self.event_direction == "up") != up or path.factor_direction is None:
                return False
        return True


class Conditions(BaseModel):
    ved: bool | None = None
    ved_direction: Literal["import", "export"] | None = None
    products: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)

    def satisfied(self, p: CompanyProfile) -> bool:
        if self.ved and not any(v.country_iso2 for v in p.ved):
            return False
        if self.ved_direction and not any(v.direction == self.ved_direction for v in p.ved):
            return False
        if any(not (p.products.get(code) and p.products[code].has) for code in self.products):
            return False
        return not (self.industries and p.industry_id not in self.industries)


class Product(BaseModel):
    id: str
    name: str
    pitch: str
    url: str | None = None
    roles: list[Role]
    triggers: list[Trigger]
    conditions: Conditions = Field(default_factory=Conditions)


class ProductsFile(BaseModel):
    version: int
    disclaimer: str
    products: list[Product]


class ProductCandidate(BaseModel):
    product_id: str
    name: str
    pitch: str
    when: str
    score: float
    path_id: str


def when_text(path: ChainPath) -> str:
    """«Когда уместен» — из совпавшего пути: канал, звено, эффект, риск/возможность."""
    if path.channel == "factor":
        arrow = "рост" if (path.factor_direction or 1) > 0 else "снижение"
        what = f"{lower_name(path.factor_name)}: {arrow}"
    else:
        what = f"{lower_name(path.industry_name)}: {EFFECT_SHORT.get(path.effect or '', path.effect or '')}"
    return f"{CHANNEL_WHEN[path.channel]} — {what} ({DIRECTION_RU[path.direction]})"


class ProductCatalog:
    def __init__(self, data: ProductsFile):
        self.data = data
        self.by_id = {p.id: p for p in data.products}
        if len(self.by_id) != len(data.products):
            raise ValueError("products.yaml: повторяющиеся id продуктов")

    @classmethod
    def load(cls, path: Path) -> ProductCatalog:
        return cls(load_yaml(path, ProductsFile))

    @property
    def disclaimer(self) -> str:
        return self.data.disclaimer

    def get(self, product_id: str) -> Product | None:
        return self.by_id.get(product_id)

    def match(self, exposure: Exposure, profile: CompanyProfile, role: Role) -> list[ProductCandidate]:
        best: dict[str, ProductCandidate] = {}
        for path in exposure.paths[:MATCH_PATHS]:
            for prod in self.data.products:
                if not prod.conditions.satisfied(profile) or not any(t.matches(path) for t in prod.triggers):
                    continue
                score = path.contribution * (ROLE_BOOST if role in prod.roles else 1.0)
                cur = best.get(prod.id)
                if cur is None or score > cur.score:
                    best[prod.id] = ProductCandidate(
                        product_id=prod.id, name=prod.name, pitch=prod.pitch,
                        when=when_text(path), score=round(score, 6), path_id=path.id,
                    )  # fmt: skip
        ordered = sorted(best.values(), key=lambda c: (-c.score, list(self.by_id).index(c.product_id)))
        return ordered[:MAX_CANDIDATES]


def products_block(candidates: list[ProductCandidate]) -> str:
    if not candidates:
        return "Кандидатов нет — не указывай product_id"
    return "\n".join(f"{c.product_id} — {c.name}: {c.pitch} Когда уместен: {c.when}." for c in candidates)
