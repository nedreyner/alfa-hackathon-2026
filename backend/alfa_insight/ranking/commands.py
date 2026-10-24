"""CLI `alfa rank all|company|event`."""

from __future__ import annotations

import time

import typer

rank_app = typer.Typer(help="Ранжирование событий для компаний.", no_args_is_help=True)


def _service():  # type: ignore[no-untyped-def]
    from alfa_insight.appctx import build_context

    ctx = build_context()
    return ctx, ctx.ranking


@rank_app.command("all")
def rank_all() -> None:
    """Пересчитать ранжирование всех событий окна для всех целевых компаний и ролей."""
    _, svc = _service()
    t = time.monotonic()
    n = svc.rank_all()
    typer.echo(f"строк rankings: {n} за {time.monotonic() - t:.1f} с")


@rank_app.command("company")
def rank_company(company_id: str = typer.Argument(...), top: int = typer.Option(10, "--top")) -> None:
    """Пересчитать одну компанию и показать лучшие события по ролям."""
    ctx, svc = _service()
    typer.echo(f"строк: {svc.rank_company(company_id)}")
    from alfa_insight.store.rankings import RankingStore

    for role in ("cfo", "treasurer", "owner"):
        typer.echo(f"\n{role}:")
        for r in RankingStore(ctx.db).top(company_id, role, limit=top):
            typer.echo(
                f"  {r['score']:.3f} {r['impact_level']:8} {r['direction']:11} [{r['event_id']}] {r['chain_preview']}"
            )


@rank_app.command("event")
def rank_event(event_id: int = typer.Argument(...)) -> None:
    """Пересчитать одно событие для всех целевых компаний."""
    _, svc = _service()
    typer.echo(f"строк: {svc.rank_events([event_id])}")
