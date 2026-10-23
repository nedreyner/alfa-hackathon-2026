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
