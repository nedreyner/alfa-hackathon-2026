"""CLI `alfa macro refresh|snapshot`."""

from __future__ import annotations

import asyncio

import typer

macro_app = typer.Typer(help="Макроданные ЦБ.", no_args_is_help=True)


@macro_app.command("refresh")
def macro_refresh() -> None:
    """Загрузить ключевую ставку и курсы 7 валют с сайта ЦБ (при ошибке — снимок, если таблица пуста)."""
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.macro import load_snapshot, refresh_macro
    from alfa_insight.store.macro import MacroStore

    ctx = build_context()
    store = MacroStore(ctx.db)
    try:
        loaded = asyncio.run(refresh_macro(store))
        typer.echo(" ".join(f"{k}={v}" for k, v in loaded.items()))
    except Exception as exc:
        n = load_snapshot(store, ctx.settings.seed_dir / "macro.json")
        typer.echo(f"ЦБ недоступен ({type(exc).__name__}); из снимка загружено точек: {n}", err=True)
    for ind in ("key_rate", "fx_cny", "fx_usd"):
        s = store.summary(ind)
        if s:
            typer.echo(f"{s.name}: {s.latest.value} {s.unit} на {s.latest.date} ({s.source})")


@macro_app.command("snapshot")
def macro_snapshot() -> None:
    """Записать data/seed/macro.json из базы."""
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.macro import write_snapshot
    from alfa_insight.store.macro import MacroStore

    ctx = build_context()
    path = ctx.settings.seed_dir / "macro.json"
    typer.echo(f"{path}: точек {write_snapshot(MacroStore(ctx.db), path)}")
