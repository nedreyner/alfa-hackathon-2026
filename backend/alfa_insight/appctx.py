"""Общий контейнер зависимостей. Поля добавляются по мере появления подсистем."""

from __future__ import annotations

from dataclasses import dataclass

from alfa_insight.settings import Settings, get_settings


@dataclass
class AppContext:
    settings: Settings


def build_context(settings: Settings | None = None) -> AppContext:
    return AppContext(settings=settings or get_settings())
