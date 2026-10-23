"""Маппинг физических колонок CSV на логическую схему (docs/03-data.md §3)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from alfa_insight.config_models import load_yaml

COMPANY_FIELDS = (
    "company_id",
    "inn",
    "name",
    "okved",
    "okved_secondary",
    "region_code",
    "region_name",
    "revenue_rub",
    "employees",
    "is_client",
    "group_id",
)
PRODUCT_FIELDS = ("company_id", "product_code", "amount_rub")
VED_FIELDS = ("company_id", "country_raw", "direction", "amount_rub")
PAYMENT_FIELDS = (
    "company_id",
    "counterparty_id",
    "counterparty_inn",
    "counterparty_name",
    "counterparty_okved",
    "direction",
    "amount_rub",
    "tx_count",
    "period",
)
PAYER_PAYEE_FIELDS = ("payer_id", "payee_id", "amount_rub", "tx_count", "period")
PRODUCT_CODES = (
    "credit",
    "leasing",
    "deposit",
    "guarantee",
    "factoring",
    "acquiring",
    "salary",
    "fx",
    "other",
)


class CsvOptions(BaseModel):
    delimiter: str = ","
    encoding: Literal["auto", "utf-8", "utf-8-sig", "cp1251"] = "auto"
    header: bool = True
    decimal: Literal[".", ","] = "."


class Transform(BaseModel):
    multiply: float | None = None
    true_values: list[str] | None = None
    map: dict[str, str] | None = None
    map_file: str | None = None
    strip_quotes: bool = False


class TableSpec(BaseModel):
    path: str
    csv: CsvOptions = Field(default_factory=CsvOptions)
    columns: dict[str, str | None] = Field(default_factory=dict)
    transforms: dict[str, Transform] = Field(default_factory=dict)


class CompaniesSpec(TableSpec):
    @model_validator(mode="after")
    def _check(self) -> CompaniesSpec:
        unknown = set(self.columns) - set(COMPANY_FIELDS)
        if unknown:
            raise ValueError(f"неизвестные поля companies: {sorted(unknown)}")
        for required in ("company_id", "okved", "revenue_rub", "is_client"):
            if not self.columns.get(required):
                raise ValueError(f"companies.columns.{required} обязателен")
        return self


class ProductsSpec(BaseModel):
    mode: Literal["long", "wide"] = "wide"
    # long
    path: str | None = None
    csv: CsvOptions = Field(default_factory=CsvOptions)
    columns: dict[str, str | None] = Field(default_factory=dict)
    # wide
    source: Literal["companies"] = "companies"
    flags: dict[str, str] = Field(default_factory=dict)
    amounts: dict[str, str] = Field(default_factory=dict)
    true_values: list[str] = Field(default_factory=lambda: ["1", "1.0", "да", "y", "yes", "true"])

    @model_validator(mode="after")
    def _check(self) -> ProductsSpec:
        if self.mode == "long" and not self.path:
            raise ValueError("products.path обязателен при mode: long")
        bad = set(self.flags) - set(PRODUCT_CODES)
        if bad:
            raise ValueError(f"неизвестные коды продуктов: {sorted(bad)}")
        return self


class VedSpec(BaseModel):
    mode: Literal["long", "wide", "none"] = "wide"
    path: str | None = None
    csv: CsvOptions = Field(default_factory=CsvOptions)
    columns: dict[str, str | None] = Field(default_factory=dict)
    source: Literal["companies"] = "companies"
    country_column: str | None = None
    direction_column: str | None = None
    split: list[str] = Field(default_factory=lambda: [",", ";"])

    @model_validator(mode="after")
    def _check(self) -> VedSpec:
        if self.mode == "long" and not self.path:
            raise ValueError("ved.path обязателен при mode: long")
        if self.mode == "wide" and not self.country_column:
            raise ValueError("ved.country_column обязателен при mode: wide")
        return self


class PaymentsSpec(TableSpec):
    mode: Literal["company_counterparty", "payer_payee"] = "company_counterparty"
    direction_values: dict[Literal["out", "in"], list[str]] | None = None
    counterparty_key: Literal["company_id", "inn"] = "company_id"
    exclude_self: bool = True
    exclude_intragroup: bool = True

    @model_validator(mode="after")
    def _check(self) -> PaymentsSpec:
        allowed = PAYMENT_FIELDS if self.mode == "company_counterparty" else PAYER_PAYEE_FIELDS
        unknown = set(self.columns) - set(allowed)
        if unknown:
            raise ValueError(f"неизвестные поля payments ({self.mode}): {sorted(unknown)}")
        required = (
            ("company_id", "counterparty_id")
            if self.mode == "company_counterparty"
            else ("payer_id", "payee_id")
        )
        for name in required:
            if not self.columns.get(name):
                raise ValueError(f"payments.columns.{name} обязателен")
        return self


class Tables(BaseModel):
    companies: CompaniesSpec
    products: ProductsSpec = Field(default_factory=ProductsSpec)
    ved: VedSpec = Field(default_factory=lambda: VedSpec(mode="none"))
    payments: PaymentsSpec


class DataMapping(BaseModel):
    profile: Literal["real", "synthetic"]
    target_revenue_rub: float = 15_000_000_000.0
    tables: Tables
    weight_basis: Literal["auto", "amount", "tx_count", "links"] = "auto"

    def source_paths(self, root: Path) -> list[Path]:
        paths = [self.tables.companies.path, self.tables.payments.path]
        if self.tables.products.mode == "long" and self.tables.products.path:
            paths.append(self.tables.products.path)
        if self.tables.ved.mode == "long" and self.tables.ved.path:
            paths.append(self.tables.ved.path)
        return [resolve_path(root, p) for p in paths]


def resolve_path(root: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def mapping_path(config_dir: Path, profile: str) -> Path:
    return config_dir / ("data_mapping.synthetic.yaml" if profile == "synthetic" else "data_mapping.yaml")


def load_mapping(config_dir: Path, profile: str) -> DataMapping:
    return load_yaml(mapping_path(config_dir, profile), DataMapping)
