"""Загрузка YAML-конфигов с валидацией Pydantic. Модели конкретных конфигов добавляются по задачам."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from alfa_insight.errors import ConfigError


def read_yaml(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"{path}: файл не найден") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: некорректный YAML: {exc}") from exc


def load_yaml[M: BaseModel](path: Path, model: type[M]) -> M:
    raw = read_yaml(path)
    try:
        return model.model_validate(raw if raw is not None else {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '<корень>'}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"{path}: {problems}", {"errors": exc.errors(include_url=False)}) from exc


# ── config/demo.yaml (docs/03-data.md §8.3) ──
class DemoVed(BaseModel):
    country: str
    direction: Literal["import", "export", "unknown"] = "unknown"


class DemoCompany(BaseModel):
    company_id: str
    name: str
    okved: str
    region_code: str
    region_name: str
    revenue_rub: float
    products: dict[str, float] = Field(default_factory=dict)
    ved: list[DemoVed] = Field(default_factory=list)
    suppliers_mix: dict[str, float]
    buyers_mix: dict[str, float]
    story: str
    default_role: Literal["cfo", "treasurer", "owner"] = "cfo"


class RoleInfo(BaseModel):
    name: str
    short: str


class PrecomputeConfig(BaseModel):
    top_k: int = 5
    min_score: float = 0.15


class DemoConfig(BaseModel):
    version: int = 1
    companies: list[DemoCompany]
    roles: dict[str, RoleInfo] = Field(default_factory=dict)
    precompute: PrecomputeConfig = Field(default_factory=PrecomputeConfig)

    def ids(self) -> list[str]:
        return [c.company_id for c in self.companies]
