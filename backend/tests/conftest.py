"""Общие фикстуры тестов. LLM всегда работает в режиме fake — к живому шлюзу тесты не ходят."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ["LLM_MODE"] = "fake"
os.environ["LLM_API_KEY"] = "test-key"

REPO_ROOT = Path(__file__).resolve().parents[2]


def _isolated_data_dir() -> Path:
    """Настройки по умолчанию (get_settings, CLI) в тестах смотрят во временный каталог, а не в data/ репозитория."""
    root = Path(tempfile.mkdtemp(prefix="alfa-test-data-"))
    (root / "runtime").mkdir()
    for name in ("reference", "synthetic", "seed"):
        (root / name).symlink_to(REPO_ROOT / "data" / name)
    return root


os.environ["DATA_DIR"] = str(_isolated_data_dir())
os.environ["INGEST_ENABLED"] = "false"

from alfa_insight.settings import Settings, get_settings, load_settings  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Iterator[Settings]:
    """Настройки с временным каталогом данных; справочники и конфиги — из репозитория."""
    data_dir = tmp_path / "data"
    (data_dir / "runtime").mkdir(parents=True)
    (data_dir / "reference").symlink_to(REPO_ROOT / "data" / "reference")
    (data_dir / "synthetic").symlink_to(REPO_ROOT / "data" / "synthetic")
    s = load_settings(data_dir=data_dir, config_dir=REPO_ROOT / "config", llm_mode="fake")
    get_settings.cache_clear()
    yield s
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def synthetic_duckdb(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """DuckDB, собранная из закоммиченной синтетики (один раз на сессию)."""
    from alfa_insight.data.build import build

    data_dir = tmp_path_factory.mktemp("synthetic_build") / "data"
    (data_dir / "runtime").mkdir(parents=True)
    (data_dir / "reference").symlink_to(REPO_ROOT / "data" / "reference")
    (data_dir / "synthetic").symlink_to(REPO_ROOT / "data" / "synthetic")
    s = load_settings(
        data_dir=data_dir, config_dir=REPO_ROOT / "config", llm_mode="fake", data_profile="synthetic"
    )
    return build(s, force=True).path


@pytest.fixture(scope="session")
def seeded_db_path(tmp_path_factory: pytest.TempPathFactory, synthetic_duckdb: Path) -> Path:
    """SQLite после загрузки seed и конвейера на FakeLLM (один раз на сессию); копируется в тесты."""
    import asyncio
    import shutil

    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.pipeline import pipeline_run
    from alfa_insight.ingest.seed import load_seed
    from alfa_insight.llm import build_router
    from alfa_insight.llm.fake import FakeBackend

    data_dir = tmp_path_factory.mktemp("seeded") / "data"
    (data_dir / "runtime").mkdir(parents=True)
    (data_dir / "reference").symlink_to(REPO_ROOT / "data" / "reference")
    (data_dir / "synthetic").symlink_to(REPO_ROOT / "data" / "synthetic")
    (data_dir / "seed").symlink_to(REPO_ROOT / "data" / "seed")
    shutil.copy(synthetic_duckdb, data_dir / "runtime" / "analytics.duckdb")
    s = load_settings(
        data_dir=data_dir, config_dir=REPO_ROOT / "config", llm_mode="fake", data_profile="synthetic"
    )
    ctx = build_context(s)
    ctx.set_router(build_router(s, ctx.db, backend=FakeBackend()))
    load_seed(ctx, REPO_ROOT / "data" / "seed" / "news.jsonl", shift_to_now=True)
    asyncio.run(pipeline_run(ctx, fetch=False))
    ctx.db.close()
    return data_dir


@pytest.fixture
def seeded_ctx(seeded_db_path: Path, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Свежая копия seed-базы для теста (контекст с FakeLLM)."""
    import shutil

    from alfa_insight.appctx import build_context
    from alfa_insight.llm import build_router
    from alfa_insight.llm.fake import FakeBackend

    data_dir = tmp_path / "data"
    (data_dir / "runtime").mkdir(parents=True)
    for name in ("reference", "synthetic", "seed"):
        (data_dir / name).symlink_to(REPO_ROOT / "data" / name)
    for f in (seeded_db_path / "runtime").iterdir():
        if f.is_file():
            shutil.copy(f, data_dir / "runtime" / f.name)
    s = load_settings(
        data_dir=data_dir, config_dir=REPO_ROOT / "config", llm_mode="fake", data_profile="synthetic"
    )
    ctx = build_context(s)
    ctx.set_router(build_router(s, ctx.db, backend=FakeBackend()))
    yield ctx
    ctx.db.close()
