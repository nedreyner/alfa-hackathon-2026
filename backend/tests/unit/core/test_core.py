from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel

from alfa_insight.config_models import load_yaml
from alfa_insight.errors import BudgetExceeded, ConfigError, NotFoundError
from alfa_insight.ids import new_id
from alfa_insight.settings import Settings, find_repo_root
from alfa_insight.timeutil import budget_day, parse_dt, to_iso


def test_repo_root_found_from_backend() -> None:
    root = find_repo_root(Path(__file__).resolve().parent)
    assert (root / "config").is_dir()
    assert (root / "backend").is_dir()


def test_settings_derived_paths(settings: Settings) -> None:
    assert settings.sqlite_path.name == "app.sqlite"
    assert settings.duckdb_path.parent == settings.runtime_dir
    assert settings.llm_mode == "fake"


def test_prod_requires_session_secret() -> None:
    with pytest.raises(ValueError, match="SESSION_SECRET"):
        Settings(app_env="prod", demo_mode=False, session_secret="short")  # type: ignore[arg-type]
    ok = Settings(app_env="prod", demo_mode=False, session_secret="x" * 40)  # type: ignore[arg-type]
    assert ok.app_env == "prod"


def test_budget_day_msk_boundary() -> None:
    """Бюджет шлюза сбрасывается в 03:00 МСК (00:00 UTC): ночь до трёх — ещё прошлые сутки."""
    assert budget_day(parse_dt("2026-10-22T21:30:00Z")).isoformat() == "2026-10-22"  # 00:30 МСК
    assert budget_day(parse_dt("2026-10-22T23:59:59Z")).isoformat() == "2026-10-22"  # 02:59 МСК
    assert budget_day(parse_dt("2026-10-23T00:00:00Z")).isoformat() == "2026-10-23"  # 03:00 МСК


def test_iso_roundtrip() -> None:
    dt = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    assert to_iso(dt) == "2026-10-22T12:00:00Z"
    assert parse_dt(to_iso(dt)) == dt


def test_new_id_unique_and_sorted() -> None:
    ids = [new_id("run") for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    assert ids == sorted(ids)
    assert all(i.startswith("run_") and len(i) == 4 + 26 for i in ids)


class _Cfg(BaseModel):
    name: str
    weight: float


def test_invalid_yaml_reports_path_and_field(tmp_path: Path) -> None:
    path = tmp_path / "cfg.yaml"
    path.write_text("name: x\nweight: not-a-number\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_yaml(path, _Cfg)
    assert str(path) in str(exc.value)
    assert "weight" in str(exc.value)


def test_broken_yaml_syntax(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("name: [unclosed\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="некорректный YAML"):
        load_yaml(path, _Cfg)


def test_error_codes() -> None:
    assert NotFoundError("x").code == "not_found"
    err = BudgetExceeded("daily")
    assert err.code == "budget_exhausted" and err.details == {"scope": "daily"}
