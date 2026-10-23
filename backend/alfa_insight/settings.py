"""Настройки окружения (pydantic-settings). Предметные настройки — в YAML (`config_models.py`)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SESSION_SECRET = "change-me-32-bytes-minimum"
MIN_SECRET_BYTES = 32


def find_repo_root(start: Path | None = None) -> Path:
    """Поднимается вверх до каталога, в котором есть `config/`."""
    candidates = [start] if start else [Path.cwd(), Path(__file__).resolve().parent]
    for base in candidates:
        for directory in [base.resolve(), *base.resolve().parents]:
            if (directory / "config").is_dir():
                return directory
    raise RuntimeError("Не найден корень репозитория: нет каталога config/ выше текущего")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore", case_sensitive=False)

    # LLM
    llm_base_url: str = ""
    llm_base_url_fallback: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_mode: Literal["live", "replay", "fake"] = "live"
    llm_daily_budget_rub: float = 450.0
    llm_interactive_reserve_rub: float = 150.0
    llm_max_run_cost_rub: float = 5.0
    budget_tz: str = "Europe/Moscow"
    verify_llm_skip_if_clean: bool = False
    tag_body_chars: int = 6000

    # Приложение
    app_env: Literal["dev", "prod"] = "dev"
    app_tz: str = "Europe/Moscow"
    log_level: str = "INFO"
    data_dir: Path | None = None
    config_dir: Path | None = None
    data_profile: Literal["synthetic", "real"] = "synthetic"
    target_revenue_rub: float = 15_000_000_000.0
    session_secret: SecretStr = SecretStr(DEFAULT_SESSION_SECRET)
    cookie_secure: bool = False
    demo_mode: bool = True
    jury_code: SecretStr = SecretStr("")
    admin_token: SecretStr = SecretStr("")

    # Агент
    agent_max_concurrent_runs: int = Field(default=4, ge=1)
    agent_run_timeout_s: int = Field(default=60, ge=1)

    # Worker
    run_worker_in_api: bool = False
    ingest_enabled: bool = True
    ingest_geo: Literal["any", "ru"] = "any"
    ingest_rss_interval_min: int = 15
    rss_max_age_days: int = 7
    prefilter_min_score: float = 3.0
    simhash_max_distance: int = 3
    cluster_sim_threshold: float = 0.30
    pipeline_tick_max_cost_rub: float = 5.0
    precompute_enabled: bool = True
    precompute_companies: str = "demo"
    seed_shift_to_now: bool = True
    init_max_cost_rub: float = 10.0
    web_port: int = 8080

    repo_root: Path = Field(default_factory=find_repo_root)

    @model_validator(mode="after")
    def _resolve_paths_and_secrets(self) -> Settings:
        if self.data_dir is None:
            self.data_dir = self.repo_root / "data"
        if self.config_dir is None:
            self.config_dir = self.repo_root / "config"
        if self.app_env == "prod" and not self.demo_mode:
            secret = self.session_secret.get_secret_value()
            if len(secret.encode()) < MIN_SECRET_BYTES or secret == DEFAULT_SESSION_SECRET:
                raise ValueError("SESSION_SECRET должен быть задан (не короче 32 байт) при APP_ENV=prod")
        return self

    @property
    def data_path(self) -> Path:
        assert self.data_dir is not None
        return self.data_dir

    @property
    def config_path(self) -> Path:
        assert self.config_dir is not None
        return self.config_dir

    @property
    def reference_dir(self) -> Path:
        return self.data_path / "reference"

    @property
    def runtime_dir(self) -> Path:
        return self.data_path / "runtime"

    @property
    def raw_dir(self) -> Path:
        return self.data_path / "raw"

    @property
    def seed_dir(self) -> Path:
        return self.data_path / "seed"

    @property
    def sqlite_path(self) -> Path:
        return self.runtime_dir / "app.sqlite"

    @property
    def duckdb_path(self) -> Path:
        return self.runtime_dir / "analytics.duckdb"


def load_settings(**overrides: Any) -> Settings:
    root = find_repo_root()
    env_file = root / ".env"
    return Settings(_env_file=env_file if env_file.exists() else None, **overrides)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
