"""CLI `alfa data …`: синтетика, сборка DuckDB, проверка данных."""

from __future__ import annotations

from pathlib import Path

import typer

data_app = typer.Typer(help="CSV → DuckDB, синтетика, проверка данных, профили.", no_args_is_help=True)


@data_app.command("synth")
def synth(
    seed: int = typer.Option(42, help="Seed генератора"),
    companies: int = typer.Option(3000, help="Всего компаний"),
    out: Path | None = typer.Option(None, help="Каталог вывода (по умолчанию data/synthetic)"),
) -> None:
    """Сгенерировать синтетические CSV (детерминированно по seed)."""
    from alfa_insight.config_models import DemoConfig, load_yaml
    from alfa_insight.data.synthetic import generate_synthetic
    from alfa_insight.reference.taxonomy import load_taxonomy
    from alfa_insight.settings import get_settings

    settings = get_settings()
    taxonomy = load_taxonomy(settings.reference_dir)
    demo = load_yaml(settings.config_path / "demo.yaml", DemoConfig)
    out_dir = out or settings.data_path / "synthetic"
    sizes = generate_synthetic(taxonomy, demo, out_dir, seed=seed, companies=companies)
    for name, size in sizes.items():
        typer.echo(f"{out_dir / name}: {size / 1024:.0f} КБ")
    typer.echo(f"Итого: {sum(sizes.values()) / 1024 / 1024:.2f} МБ")


@data_app.command("build")
def build_cmd(
    force: bool = typer.Option(False, "--force", help="Пересобрать, даже если исходники не менялись"),
) -> None:
    """Собрать analytics.duckdb из CSV по маппингу текущего DATA_PROFILE."""
    from alfa_insight.data.build import build
    from alfa_insight.settings import get_settings

    settings = get_settings()
    result = build(settings, force=force)
    if result.skipped:
        typer.echo(f"{result.path}: исходники не менялись, сборка пропущена (--force для пересборки)")
        return
    meta = result.meta
    typer.echo(
        f"{result.path}: профиль {meta['data_profile']}, компаний {meta['companies_rows']}, "
        f"платежей {meta['payments_kept']}, база весов {meta['weight_basis']}"
    )


@data_app.command("validate")
def validate_cmd() -> None:
    """Проверить собранные данные: таблица в stdout, data_quality.json, таблица data_quality."""
    from alfa_insight.data.validate import format_table, validate_file
    from alfa_insight.settings import get_settings

    settings = get_settings()
    checks = validate_file(settings.duckdb_path, settings.runtime_dir / "data_quality.json")
    typer.echo(format_table(checks))
    errors = [c.check for c in checks if c.status == "error"]
    if errors:
        typer.echo(f"Ошибки: {', '.join(errors)}", err=True)
        raise typer.Exit(1)
