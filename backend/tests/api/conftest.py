from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alfa_insight.api.app import create_app
from alfa_insight.appctx import AppContext, build_context
from alfa_insight.llm import build_router
from alfa_insight.llm.fake import FakeBackend
from alfa_insight.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def make_ctx(tmp_path: Path, duckdb: Path | None, **overrides: object) -> AppContext:
    data_dir = tmp_path / "data"
    (data_dir / "runtime").mkdir(parents=True, exist_ok=True)
    for name in ("reference", "synthetic", "seed"):
        if not (data_dir / name).exists():
            (data_dir / name).symlink_to(REPO_ROOT / "data" / name)
    if duckdb is not None:
        shutil.copy(duckdb, data_dir / "runtime" / "analytics.duckdb")
    s = load_settings(
        data_dir=data_dir,
        config_dir=REPO_ROOT / "config",
        llm_mode="fake",
        data_profile="synthetic",
        **overrides,
    )
    ctx = build_context(s)
    ctx.set_router(build_router(s, ctx.db, backend=FakeBackend()))
    return ctx


@pytest.fixture
def api_ctx(tmp_path: Path, synthetic_duckdb: Path) -> AppContext:
    return make_ctx(tmp_path, synthetic_duckdb)


@pytest.fixture
def client(api_ctx: AppContext) -> Iterator[TestClient]:
    with TestClient(create_app(api_ctx, run_worker=False)) as c:
        yield c
