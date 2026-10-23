"""Таксономия: отрасли, факторы, эффекты, типы событий, страны. Загрузка, проверка ссылок, поиск."""

from __future__ import annotations

import re
from functools import cached_property
from pathlib import Path

from alfa_insight.config_models import load_yaml
from alfa_insight.errors import ConfigError
from alfa_insight.reference.models import (
    CHANNELS,
    EFFECT_IDS,
    CountriesFile,
    Country,
    EffectsFile,
    EventType,
    EventTypesFile,
    Factor,
    FactorsFile,
    IndustriesFile,
    Industry,
    InjectionPatternsFile,
    MatrixCell,
    PrefilterLexicon,
)

UNKNOWN = "unknown"
_QUOTES = "«»\"'“”„"


def normalize_okved(code: str | None) -> str:
    """Убрать пробелы, `,` → `.`, удалить хвостовые точки."""
    if code is None:
        return ""
    text = re.sub(r"\s+", "", str(code)).replace(",", ".").rstrip(".")
    return text


def normalize_country_name(raw: str) -> str:
    text = raw.strip().lower().replace("ё", "е")
    text = text.translate({ord(q): None for q in _QUOTES})
    return re.sub(r"\s+", " ", text).strip()


class Taxonomy:
    def __init__(self, reference_dir: Path):
        self.dir = reference_dir
        self._industries = load_yaml(reference_dir / "industries.yaml", IndustriesFile)
        self._factors = load_yaml(reference_dir / "factors.yaml", FactorsFile)
        self._effects = load_yaml(reference_dir / "effects.yaml", EffectsFile)
        self._event_types = load_yaml(reference_dir / "event_types.yaml", EventTypesFile)
        self._countries = load_yaml(reference_dir / "countries.yaml", CountriesFile)
        self.prefilter = load_yaml(reference_dir / "prefilter_lexicon.yaml", PrefilterLexicon)
        self.injection = load_yaml(reference_dir / "injection_patterns.yaml", InjectionPatternsFile)

        self.industries: dict[str, Industry] = {i.id: i for i in self._industries.industries}
        self.factors: dict[str, Factor] = {f.id: f for f in self._factors.factors}
        self.effects: dict[str, str] = {e.id: e.meaning for e in self._effects.effects}
        self.matrix: dict[str, dict[str, MatrixCell]] = {str(k): v for k, v in self._effects.matrix.items()}
        self.event_types: dict[str, EventType] = {e.id: e for e in self._event_types.event_types}
        self.countries: dict[str, Country] = {c.iso2: c for c in self._countries.countries}
        self._validate()

        self._prefix_index: list[tuple[str, str]] = sorted(
            ((p, ind.id) for ind in self.industries.values() for p in ind.okved_prefixes),
            key=lambda item: -len(item[0]),
        )
        self._country_index: dict[str, str] = {}
        for c in self.countries.values():
            self._country_index[c.iso2.lower()] = c.iso2
            for name in c.names:
                self._country_index[normalize_country_name(name)] = c.iso2

    # ── проверки ──
    def _validate(self) -> None:
        def fail(file: str, msg: str) -> None:
            raise ConfigError(f"{self.dir / file}: {msg}")

        if UNKNOWN not in self.industries:
            fail("industries.yaml", "нет отрасли unknown")
        for ind in self.industries.values():
            for fid in ind.factor_sensitivity:
                if fid not in self.factors:
                    fail("industries.yaml", f"{ind.id}.factor_sensitivity: неизвестный фактор {fid!r}")
            for field in ("typical_suppliers", "typical_buyers"):
                for iid in getattr(ind, field):
                    if iid not in self.industries:
                        fail("industries.yaml", f"{ind.id}.{field}: неизвестная отрасль {iid!r}")
        seen: dict[str, str] = {}
        for ind in self.industries.values():
            for p in ind.okved_prefixes:
                if p in seen:
                    fail("industries.yaml", f"префикс {p!r} у {seen[p]} и {ind.id}")
                seen[p] = ind.id
        if set(self.effects) != set(EFFECT_IDS):
            fail("effects.yaml", f"ожидаются эффекты {sorted(EFFECT_IDS)}")
        for ch in CHANNELS:
            cells = self.matrix.get(ch, {})
            missing = set(EFFECT_IDS) - set(cells)
            if missing:
                fail("effects.yaml", f"matrix.{ch}: нет эффектов {sorted(missing)}")
        for et in self.event_types.values():
            for fid in et.default_factors:
                if fid not in self.factors:
                    fail("event_types.yaml", f"{et.id}.default_factors: неизвестный фактор {fid!r}")

    # ── поиск ──
    def match_okved(self, code: str | None) -> str:
        norm = normalize_okved(code)
        if not norm:
            return UNKNOWN
        for prefix, iid in self._prefix_index:
            if (
                norm == prefix
                or norm.startswith(prefix + ".")
                or (len(prefix) > 2 and norm.startswith(prefix))
            ):
                return iid
        return UNKNOWN

    def industry(self, industry_id: str) -> Industry:
        try:
            return self.industries[industry_id]
        except KeyError as exc:
            raise KeyError(f"неизвестная отрасль {industry_id!r}") from exc

    def factor(self, factor_id: str) -> Factor:
        try:
            return self.factors[factor_id]
        except KeyError as exc:
            raise KeyError(f"неизвестный фактор {factor_id!r}") from exc

    def country_by_name(self, raw: str | None) -> Country | None:
        if not raw:
            return None
        iso = self._country_index.get(normalize_country_name(raw))
        return self.countries[iso] if iso else None

    def typical_suppliers(self, industry_id: str) -> dict[str, float]:
        return _normalized(self.industry(industry_id).typical_suppliers)

    def typical_buyers(self, industry_id: str) -> dict[str, float]:
        return _normalized(self.industry(industry_id).typical_buyers)

    def matrix_cell(self, channel: str, effect: str) -> MatrixCell:
        return self.matrix[channel][effect]

    @cached_property
    def version(self) -> int:
        return sum(
            f.version
            for f in (
                self._industries,
                self._factors,
                self._effects,
                self._event_types,
                self._countries,
                self.prefilter,
                self.injection,
            )
        )


def _normalized(shares: dict[str, float]) -> dict[str, float]:
    total = sum(shares.values())
    return {k: v / total for k, v in shares.items()} if total > 0 else {}


def load_taxonomy(reference_dir: Path) -> Taxonomy:
    return Taxonomy(reference_dir)
