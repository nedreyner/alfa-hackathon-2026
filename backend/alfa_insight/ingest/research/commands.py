"""CLI `alfa research ingest`."""

from __future__ import annotations

import asyncio

import typer

research_app = typer.Typer(help="Аналитика Альфа-Банка из PDF.", no_args_is_help=True)


@research_app.command("ingest")
def research_ingest(
    max_cost: float | None = typer.Option(None, "--max-cost", help="Лимит стоимости, ₽"),
    vision: bool = typer.Option(
        False, "--vision", help="Описывать графики (P2; сканы и так распознаются целиком)"
    ),
    directory: str | None = typer.Option(
        None, "--dir", help="Каталог с PDF (по умолчанию data/raw/research)"
    ),
) -> None:
    """Разобрать PDF: текст или распознавание сканов, чанки, факты, прогнозы и позиции банка."""
    from pathlib import Path

    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.research.pipeline import ingest_research
    from alfa_insight.store.research import ResearchStore

    ctx = build_context()
    path = Path(directory) if directory else ctx.settings.raw_dir / "research"
    if not path.exists():
        typer.echo(f"{path}: каталога нет, пропуск")
        return
    stats = asyncio.run(ingest_research(ctx, path, max_cost_rub=max_cost))
    typer.echo(
        f"документов {stats.docs_total}: обработано {stats.docs_processed}, без изменений {stats.docs_skipped}; "
        f"распознано страниц {stats.pages_ocr}, чанков {stats.chunks}, элементов {stats.items}, {stats.cost_rub:.2f} ₽"
    )
    for err in stats.errors:
        typer.echo(f"ошибка: {err}", err=True)
    typer.echo(f"в базе: {ResearchStore(ctx.db).counts()}")
