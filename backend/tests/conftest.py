"""Общие фикстуры тестов. LLM всегда работает в режиме fake — к живому шлюзу тесты не ходят."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ["LLM_MODE"] = "fake"
os.environ["LLM_API_KEY"] = "test-key"

from alfa_insight.settings import Settings, get_settings, load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    """Настройки с временным каталогом данных; справочники и конфиги — из репозитория."""
    data_dir = tmp_path / "data"
    (data_dir / "runtime").mkdir(parents=True)
    (data_dir / "reference").symlink_to(REPO_ROOT / "data" / "reference")
    s = load_settings(data_dir=data_dir, config_dir=REPO_ROOT / "config", llm_mode="fake")
    get_settings.cache_clear()
    yield s
    get_settings.cache_clear()
