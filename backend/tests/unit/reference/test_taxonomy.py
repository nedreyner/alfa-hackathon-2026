from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from alfa_insight.errors import ConfigError
from alfa_insight.reference.models import CHANNELS, EFFECT_IDS
from alfa_insight.reference.taxonomy import Taxonomy

REF = Path(__file__).resolve().parents[4] / "data" / "reference"


@pytest.fixture(scope="module")
def tax() -> Taxonomy:
    return Taxonomy(REF)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("46.72.21", "wholesale_metals"),
        ("46.7", "wholesale_other"),
        ("46.75.1", "wholesale_chemicals"),
        ("41.20", "construction_buildings"),
        ("45.11", "auto_trade"),
        ("64.91", "finance_insurance"),
        ("09.10", "oil_gas"),
        ("09.90", "mining_metal_ores"),
        (" 46,72 ", "wholesale_metals"),
        ("", "unknown"),
        (None, "unknown"),
        ("46.51", "wholesale_tech_equipment"),
        ("52.29", "transport_logistics"),
        ("62.01", "it_telecom"),
    ],
)
def test_match_okved(tax: Taxonomy, code: str | None, expected: str) -> None:
    assert tax.match_okved(code) == expected


def test_countries(tax: Taxonomy) -> None:
    assert tax.country_by_name("Китайская Народная Республика").iso2 == "CN"  # type: ignore[union-attr]
    assert tax.country_by_name("КИТАЙ").iso2 == "CN"  # type: ignore[union-attr]
    assert tax.country_by_name("Турция").iso2 == "TR"  # type: ignore[union-attr]
    assert tax.country_by_name("«ОАЭ»").iso2 == "AE"  # type: ignore[union-attr]
    assert tax.country_by_name("Атлантида") is None


def test_matrix_complete_and_shares_normalized(tax: Taxonomy) -> None:
    for ch in CHANNELS:
        assert set(tax.matrix[ch]) == set(EFFECT_IDS)
    assert len(tax.industries) == 44
    sup = tax.typical_suppliers("wholesale_metals")
    assert abs(sum(sup.values()) - 1) < 1e-9 and sup["metallurgy"] == pytest.approx(0.8)
    assert tax.typical_buyers("retail") == {}
    assert tax.version >= 7


def test_broken_factor_reference(tmp_path: Path) -> None:
    ref = tmp_path / "reference"
    shutil.copytree(REF, ref)
    path = ref / "industries.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "customs_tariffs: [0.5, -1]", "no_such_factor: [0.5, -1]", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="no_such_factor"):
        Taxonomy(ref)
