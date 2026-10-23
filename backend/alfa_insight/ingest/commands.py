"""CLI `alfa ingest …`, `alfa pipeline …`, `alfa seed …`."""

from __future__ import annotations

import asyncio

import typer

ingest_app = typer.Typer(help="Сбор новостей: RSS, seed.", no_args_is_help=True)


@ingest_app.command("rss")
def ingest_rss(source: str | None = typer.Option(None, "--source", help="Только один источник")) -> None:
    """Собрать RSS из включённых источников."""
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.rss import collect_rss
    from alfa_insight.store.news import NewsStore

    ctx = build_context()
    results = asyncio.run(
        collect_rss(
            ctx.sources,
            NewsStore(ctx.db),
            ctx.kv,
            ingest_geo=ctx.settings.ingest_geo,
            max_age_days=ctx.settings.rss_max_age_days,
            only=source,
        )
    )
    skipped = [s.id for s in ctx.sources.sources if s.geo == "ru" and ctx.settings.ingest_geo != "ru"]
    for r in results:
        state = "ok" if r.ok else f"ошибка: {r.error}"
        extra = " (не изменилась)" if r.not_modified else ""
        typer.echo(f"{r.source_id:12} {state}{extra}  записей {r.items_total}, новых {r.items_new}")
    if skipped and source is None:
        typer.echo(f"Пропущены (geo: ru при INGEST_GEO=any): {', '.join(skipped)}")
