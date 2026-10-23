from __future__ import annotations

from pathlib import Path

import pytest

from alfa_insight.data.counterparties import CounterpartyReader
from alfa_insight.data.profiles import ProfileStore
from alfa_insight.db.duck import DuckReader
from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.errors import NotFoundError
from alfa_insight.reference.taxonomy import Taxonomy
from alfa_insight.store.profiles import ProfileOverridesRepo

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def env(
    tmp_path: Path, synthetic_duckdb: Path
) -> tuple[ProfileStore, ProfileOverridesRepo, CounterpartyReader]:
    db = SqliteDB(tmp_path / "app.sqlite")
    db.migrate()
    tax = Taxonomy(ROOT / "data" / "reference")
    duck = DuckReader(synthetic_duckdb)
    repo = ProfileOverridesRepo(db)
    return (
        ProfileStore(duck, repo, tax, demo_ids=["SYN-DEMO-01", "SYN-DEMO-02"]),
        repo,
        CounterpartyReader(duck, tax),
    )


def test_get_caches_and_invalidate(
    env: tuple[ProfileStore, ProfileOverridesRepo, CounterpartyReader],
) -> None:
    store, repo, _ = env
    first = store.get("SYN-DEMO-02")
    assert store.get("SYN-DEMO-02") is first
    repo.upsert("SYN-DEMO-02", "notes", "Строим жильё в Самаре", "s1")
    assert store.get("SYN-DEMO-02") is first  # кеш до invalidate
    store.invalidate("SYN-DEMO-02")
    updated = store.get("SYN-DEMO-02")
    assert updated.notes == "Строим жильё в Самаре"
    assert "override.notes" in updated.feature_keys()
    assert updated.profile_version != first.profile_version
    with pytest.raises(NotFoundError):
        store.get("NO-SUCH")


def test_industry_override(env: tuple[ProfileStore, ProfileOverridesRepo, CounterpartyReader]) -> None:
    store, repo, _ = env
    base = store.get("SYN-DEMO-02")
    repo.upsert("SYN-DEMO-02", "industry_id", "wholesale_metals", "s1")
    store.invalidate("SYN-DEMO-02")
    p = store.get("SYN-DEMO-02")
    assert p.industry_id == "wholesale_metals" and p.industry_name == "Опт: металлы и руды"
    main = next(f for f in p.features if f.key == "industry.main")
    assert main.source == "override" and "Опт: металлы" in main.value
    assert p.factor("customs_tariffs") is not None and base.factor("customs_tariffs") is None
    assert p.profile_version != base.profile_version


def test_ved_override_adds_fx(env: tuple[ProfileStore, ProfileOverridesRepo, CounterpartyReader]) -> None:
    store, repo, _ = env
    base = store.get("SYN-DEMO-02")
    assert base.factor("fx_cny") is None and base.factor("cross_border_payments") is None
    repo.upsert("SYN-DEMO-02", "ved", [{"country_iso2": "CN", "direction": "import"}], "s1")
    repo.upsert("SYN-DEMO-02", "products", {"deposit": True, "leasing": False}, "s1")
    store.invalidate("SYN-DEMO-02")
    p = store.get("SYN-DEMO-02")
    assert p.factor("fx_cny") is not None and p.factor("cross_border_payments") is not None
    assert "ved.country.CN" in p.feature_keys()
    assert p.products["deposit"].has and not p.products["leasing"].has
    assert "products.leasing" not in p.feature_keys()
    repo.delete("SYN-DEMO-02", "ved")
    repo.delete("SYN-DEMO-02", "products")
    store.invalidate()
    assert store.get("SYN-DEMO-02").profile_version == base.profile_version


def test_list_targets_and_counterparties(
    env: tuple[ProfileStore, ProfileOverridesRepo, CounterpartyReader],
) -> None:
    store, _, cps = env
    targets = store.list_targets()
    assert [t.company_id for t in targets[:2]] == ["SYN-DEMO-01", "SYN-DEMO-02"]
    assert targets[0].is_demo and not targets[-1].is_demo
    top = cps.top("SYN-DEMO-02", "suppliers", limit=5)
    assert len(top) == 5 and [c.rank for c in top] == [1, 2, 3, 4, 5]
    assert all(c.direction == "out" for c in top)
    metal = cps.top("SYN-DEMO-02", "out", industry_id="metallurgy", limit=50)
    assert metal and all(c.industry_id == "metallurgy" for c in metal)
    assert 0 < sum(c.share for c in metal) <= 0.345  # топ-50 по всем отраслям — часть металлургии
    buyers = cps.top("SYN-DEMO-02", "buyers", limit=50)
    assert all(c.name == "ИП (контрагент)" or not c.name.upper().startswith("ИП ") for c in buyers)
    assert any(c.name == "ИП (контрагент)" for c in buyers)
