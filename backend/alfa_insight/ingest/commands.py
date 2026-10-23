"""CLI `alfa ingest …`, `alfa pipeline …`, `alfa seed …`."""

from __future__ import annotations

import asyncio

import typer
from pydantic import BaseModel

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


@ingest_app.command("seed")
def ingest_seed(
    shift_to_now: bool = typer.Option(False, "--shift-to-now", help="Сдвинуть даты: самая свежая — now−2ч"),
    path: str | None = typer.Option(None, "--path", help="Файл seed (по умолчанию data/seed/news.jsonl)"),
) -> None:
    """Загрузить seed-новости в базу (status=extracted). Повторный запуск не создаёт дублей."""
    from pathlib import Path

    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.seed import load_seed

    ctx = build_context()
    file = Path(path) if path else ctx.settings.seed_dir / "news.jsonl"
    res = load_seed(ctx, file, shift_to_now=shift_to_now)
    typer.echo(
        f"{file}: записей {res['total']}, загружено новых {res['inserted']}, сдвинуто дат {res['shifted']}"
    )


seed_app = typer.Typer(help="Seed-набор новостей: сбор и кураторство.", no_args_is_help=True)


@seed_app.command("collect")
def seed_collect(
    out: str = typer.Option("data/seed/news.jsonl", "--out"),
    max_items: int = typer.Option(400, "--max", help="Максимум новых записей за запуск"),
    extra_feeds: str | None = typer.Option(None, "--feeds", help="Доп. YAML с лентами (как sources.yaml)"),
    max_age_days: int = typer.Option(45, "--max-age-days", help="Брать записи не старше N дней"),
) -> None:
    """RSS → полный текст → префильтр (без LLM) → дописать в JSONL (дедупликация по URL)."""
    from pathlib import Path

    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.seed_collect import collect_seed

    ctx = build_context()
    target = Path(out) if Path(out).is_absolute() else ctx.settings.repo_root / out
    feeds = Path(extra_feeds) if extra_feeds else None
    if feeds is not None and not feeds.is_absolute():
        feeds = ctx.settings.repo_root / feeds
    res = asyncio.run(
        collect_seed(ctx, target, max_items=max_items, extra_feeds=feeds, max_age_days=max_age_days)
    )
    typer.echo(f"{target}: было {res['before']}, добавлено {res['added']}, прошли префильтр {res['passed']}")


@seed_app.command("curate")
def seed_curate(path: str = typer.Option("data/seed/news.jsonl", "--path")) -> None:
    """Интерактивная разметка story и expect_relevant для записей без разметки куратора."""
    from pathlib import Path

    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.seed import read_seed, write_seed

    ctx = build_context()
    file = Path(path) if Path(path).is_absolute() else ctx.settings.repo_root / path
    items = read_seed(file)
    demo_ids = ctx.demo.ids()
    typer.echo("История: номер демо-компании 1–6 или пусто; релевантность: y/n; d — удалить; q — выход")
    for i, c in enumerate(ctx.demo.companies, 1):
        typer.echo(f"  {i}. {c.company_id}: {c.story}")
    kept = []
    for idx, it in enumerate(items):
        if it.expect_relevant is not None:
            kept.append(it)
            continue
        typer.echo(
            f"\n[{idx + 1}/{len(items)}] {it.publisher} · {it.published_at}\n{it.title}\n{(it.body or '')[:300]}"
        )
        answer = typer.prompt("история / d / q", default="", show_default=False).strip().lower()
        if answer == "q":
            kept.extend(items[idx:])
            break
        if answer == "d":
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(demo_ids):
            it.story = demo_ids[int(answer) - 1]
        rel = typer.prompt("релевантна? y/n", default="y").strip().lower()
        it.expect_relevant = rel.startswith("y")
        kept.append(it)
    write_seed(file, kept)
    typer.echo(f"{file}: сохранено {len(kept)}")


pipeline_app = typer.Typer(
    help="Конвейер новостей: префильтр, разметка, кластеризация.", no_args_is_help=True
)


def _print_stats(stats: BaseModel) -> None:
    typer.echo(
        " ".join(
            f"{k}={v:.4f}" if isinstance(v, float) else f"{k}={v}" for k, v in stats.model_dump().items()
        )
    )  # type: ignore[attr-defined]


@pipeline_app.command("tick")
def pipeline_tick_cmd(
    max_tag: int = typer.Option(40, "--max-tag"),
    max_cost: float | None = typer.Option(None, "--max-cost", help="Лимит стоимости разметки, ₽"),
    no_fetch: bool = typer.Option(False, "--no-fetch", help="Не скачивать полный текст"),
) -> None:
    """Один тик конвейера."""
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.pipeline import pipeline_tick

    ctx = build_context()
    _print_stats(asyncio.run(pipeline_tick(ctx, max_tag=max_tag, max_cost_rub=max_cost, fetch=not no_fetch)))


@pipeline_app.command("run")
def pipeline_run_cmd(
    until: str = typer.Option("clustered", "--until", help="extracted | clustered"),
    max_cost: float | None = typer.Option(None, "--max-cost", help="Лимит стоимости разметки, ₽"),
    no_fetch: bool = typer.Option(False, "--no-fetch"),
) -> None:
    """Тики, пока есть работа (или до лимита стоимости)."""
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.pipeline import pending_work, pipeline_run

    ctx = build_context()
    _print_stats(asyncio.run(pipeline_run(ctx, until=until, max_cost_rub=max_cost, fetch=not no_fetch)))
    typer.echo(f"Осталось: {pending_work(ctx)}")
