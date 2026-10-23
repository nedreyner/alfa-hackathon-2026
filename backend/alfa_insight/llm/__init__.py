"""LLM-слой. Все вызовы моделей идут через `LLMRouter` (кеш, бюджет, цепочки моделей)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from alfa_insight.config_models import load_yaml
from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.llm.budget import BudgetGuard
from alfa_insight.llm.cache import LLMCache
from alfa_insight.llm.client import GatewayClient
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.llm.router import LiveBackend, LLMBackend, LLMRouter, ReplayBackend
from alfa_insight.llm.types import ModelsConfig
from alfa_insight.settings import Settings, get_settings
from alfa_insight.store.llm import LLMStore

__all__ = ["LLMRouter", "build_router", "get_router", "load_models_config"]


def load_models_config(config_dir: Path) -> ModelsConfig:
    return load_yaml(config_dir / "models.yaml", ModelsConfig)


def load_probe_capabilities(runtime_dir: Path) -> dict[str, dict[str, Any]]:
    path = runtime_dir / "model_capabilities.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: item.get("capabilities", {}) for key, item in data.get("models", {}).items()}


def build_router(settings: Settings, db: SqliteDB, *, backend: LLMBackend | None = None) -> LLMRouter:
    config = load_models_config(settings.config_path)
    store = LLMStore(db)
    budget = BudgetGuard(
        store,
        daily_limit_rub=settings.llm_daily_budget_rub,
        interactive_reserve_rub=settings.llm_interactive_reserve_rub,
        max_run_cost_rub=settings.llm_max_run_cost_rub,
        tz=settings.budget_tz,
    )
    if backend is None:
        if settings.llm_mode == "fake":
            backend = FakeBackend()
        elif settings.llm_mode == "replay":
            backend = ReplayBackend()
        else:
            backend = LiveBackend(
                GatewayClient(
                    settings.llm_base_url,
                    settings.llm_base_url_fallback or None,
                    settings.llm_api_key.get_secret_value(),
                    config.gateway.timeout_s,
                    config.gateway.connect_timeout_s,
                    config.gateway.token_param,
                )
            )
    return LLMRouter(
        config,
        backend,
        LLMCache(store),
        budget,
        mode=settings.llm_mode,
        capabilities_override=load_probe_capabilities(settings.runtime_dir),
        budget_tz=settings.budget_tz,
    )


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    settings = get_settings()
    db = SqliteDB(settings.sqlite_path)
    db.migrate()
    return build_router(settings, db)
