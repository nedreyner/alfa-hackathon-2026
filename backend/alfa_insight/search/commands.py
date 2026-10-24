"""CLI `alfa search news|research`."""

from __future__ import annotations

import typer

search_app = typer.Typer(help="Поиск по новостям и аналитике.", no_args_is_help=True)


@search_app.command("news")
def search_news_cmd(
    query: str = typer.Argument(...),
    company: str | None = typer.Option(None, "--company"),
    days: int = typer.Option(30, "--days"),
    limit: int = typer.Option(5, "--limit"),
) -> None:
    """Поиск новостей (bm25 × свежесть, по одному результату на событие)."""
    from alfa_insight.appctx import build_context
    from alfa_insight.search.news import search_news

    ctx = build_context()
    for h in search_news(ctx.db, query, company_id=company, days=days, limit=limit):
        typer.echo(
            f"{h.score:7.3f}  {h.published_at:%Y-%m-%d}  {h.publisher:12.12}  [{h.event_id}] {h.title}"
        )


@search_app.command("research")
def search_research_cmd(query: str = typer.Argument(...), limit: int = typer.Option(4, "--limit")) -> None:
    """Поиск по аналитике Альфа-Банка."""
    from alfa_insight.appctx import build_context
    from alfa_insight.search.research import search_research

    ctx = build_context()
    for h in search_research(ctx.db, query, limit=limit):
        typer.echo(
            f"{h.score:7.3f}  {h.source_id}  {h.doc_title[:60]} · {h.heading or ''}\n         {h.text[:200]}"
        )
