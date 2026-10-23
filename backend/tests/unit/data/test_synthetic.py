from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path

import pytest

from alfa_insight.config_models import DemoConfig, load_yaml
from alfa_insight.data.naming import match_name_industry
from alfa_insight.data.synthetic import generate_synthetic
from alfa_insight.reference.taxonomy import Taxonomy

ROOT = Path(__file__).resolve().parents[4]
TARGET = 15e9


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return Taxonomy(ROOT / "data" / "reference")


@pytest.fixture(scope="module")
def demo() -> DemoConfig:
    return load_yaml(ROOT / "config" / "demo.yaml", DemoConfig)


@pytest.fixture(scope="module")
def synth_dir(tmp_path_factory: pytest.TempPathFactory, tax: Taxonomy, demo: DemoConfig) -> Path:
    out = tmp_path_factory.mktemp("synth")
    generate_synthetic(tax, demo, out, seed=42)
    return out


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _digest(directory: Path) -> str:
    h = hashlib.sha256()
    for name in sorted(p.name for p in directory.glob("*.csv")):
        h.update(name.encode() + (directory / name).read_bytes())
    return h.hexdigest()


def test_deterministic(tmp_path: Path, tax: Taxonomy, demo: DemoConfig, synth_dir: Path) -> None:
    generate_synthetic(tax, demo, tmp_path, seed=42)
    assert _digest(tmp_path) == _digest(synth_dir)


def test_committed_files_match_seed_42(synth_dir: Path) -> None:
    committed = ROOT / "data" / "synthetic"
    assert _digest(committed) == _digest(synth_dir), "перегенерируйте: uv run alfa data synth"


def test_size_limit(synth_dir: Path) -> None:
    assert sum(p.stat().st_size for p in synth_dir.glob("*.csv")) <= 8 * 1024 * 1024


def test_target_distributions(synth_dir: Path, tax: Taxonomy) -> None:
    companies = _rows(synth_dir / "companies.csv")
    targets = {c["company_id"]: c for c in companies if float(c["revenue_rub"]) >= TARGET}
    n = len(targets)
    assert 35 <= n <= 45
    assert all(c["company_id"].startswith("SYN-") for c in companies)
    assert sum(c["is_client"] == "true" for c in targets.values()) / n == pytest.approx(0.94, abs=0.05)
    groups: dict[str, int] = defaultdict(int)
    for c in targets.values():
        ind = tax.match_okved(c["okved"])
        group = (
            "wholesale"
            if ind.startswith("wholesale")
            else "construction"
            if ind.startswith("construction")
            else "auto"
            if ind == "auto_trade"
            else "other"
        )
        groups[group] += 1
    for group, share in {"wholesale": 0.54, "construction": 0.17, "auto": 0.09, "other": 0.20}.items():
        assert groups[group] / n == pytest.approx(share, abs=0.05), group
    products = _rows(synth_dir / "products.csv")
    for code, share in {"credit": 0.43, "leasing": 0.62}.items():
        has = {p["company_id"] for p in products if p["product_code"] == code} & set(targets)
        assert len(has) / n == pytest.approx(share, abs=0.05), code
    ved = {v["company_id"] for v in _rows(synth_dir / "ved.csv")} & set(targets)
    assert len(ved) / n == pytest.approx(0.5, abs=0.05)


def test_inn_checksums(synth_dir: Path) -> None:
    for c in _rows(synth_dir / "companies.csv")[:500]:
        d = [int(x) for x in c["inn"]]
        assert len(d) == 10 and c["inn"].startswith("00")
        assert sum(a * b for a, b in zip(d[:9], [2, 4, 10, 3, 5, 9, 4, 6, 8], strict=True)) % 11 % 10 == d[9]


def test_demo_mixes_exact(synth_dir: Path, tax: Taxonomy, demo: DemoConfig) -> None:
    okved = {c["company_id"]: c["okved"] for c in _rows(synth_dir / "companies.csv")}
    flows: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for p in _rows(synth_dir / "payments.csv"):
        cp = p["counterparty_id"]
        if cp in okved:
            ind = tax.match_okved(okved[cp])
        elif p["counterparty_okved"]:
            ind = tax.match_okved(p["counterparty_okved"])
        else:
            ind = match_name_industry(p["counterparty_name"], tax) or "unknown"
        flows[(p["company_id"], p["direction"])][ind] += float(p["amount_rub"])
    for d in demo.companies:
        for direction, mix in (("out", d.suppliers_mix), ("in", d.buyers_mix)):
            got = flows[(d.company_id, direction)]
            total = sum(got.values())
            for ind, share in mix.items():
                assert got.get(ind, 0) / total == pytest.approx(share, abs=0.01), (
                    d.company_id,
                    direction,
                    ind,
                )
