"""Загрузка YAML-конфигов с валидацией Pydantic. Модели конкретных конфигов добавляются по задачам."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

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
