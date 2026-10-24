"""CLI `alfa`: точка входа для всех операций с данными, LLM, конвейером и сервисами."""

from __future__ import annotations

import typer

from alfa_insight import __version__
from alfa_insight.data.commands import data_app
from alfa_insight.demo_commands import demo_app
from alfa_insight.evaluation.commands import eval_app
from alfa_insight.ingest.commands import ingest_app, pipeline_app, seed_app
from alfa_insight.ingest.macro_commands import macro_app
from alfa_insight.ingest.research.commands import research_app
from alfa_insight.llm.commands import llm_app
from alfa_insight.ranking.commands import rank_app
from alfa_insight.search.commands import search_app

app = typer.Typer(
    name="alfa",
    help="Альфа Инсайт: данные, LLM, конвейер новостей, агент и сервисы.",
    no_args_is_help=True,
    add_completion=False,
)

NOT_IMPLEMENTED_EXIT = 2


def _not_implemented(name: str) -> None:
    typer.echo(f"{name}: not implemented", err=True)
    raise typer.Exit(NOT_IMPLEMENTED_EXIT)


def _stub_group(name: str, help_text: str) -> typer.Typer:
    group = typer.Typer(name=name, help=help_text, invoke_without_command=True)

    @group.callback()
    def _callback(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            _not_implemented(name)

    return group


GROUPS: dict[str, str] = {}

for _name, _help in GROUPS.items():
    app.add_typer(_stub_group(_name, _help), name=_name)


api_app = typer.Typer(help="API: OpenAPI-схема и служебные команды.", no_args_is_help=True)
app.add_typer(api_app, name="api")


@api_app.command("openapi")
def api_openapi(
    out: str = typer.Option("../frontend/openapi.json", "--out", help="Куда записать схему"),
) -> None:
    """Выгрузить OpenAPI-схему без запуска сервера."""
    import json
    from pathlib import Path

    from alfa_insight.api.app import create_app

    schema = create_app().openapi()
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(
        f"{path}: путей {len(schema.get('paths', {}))}, схем {len(schema.get('components', {}).get('schemas', {}))}"
    )


@api_app.command("serve")
def api_serve(
    host: str = typer.Option("0.0.0.0", "--host"), port: int = typer.Option(8000, "--port")
) -> None:
    """Запустить API (uvicorn)."""
    import uvicorn

    uvicorn.run("alfa_insight.api.app:create_app", factory=True, host=host, port=port, proxy_headers=True)


app.add_typer(data_app, name="data")
app.add_typer(llm_app, name="llm")
app.add_typer(ingest_app, name="ingest")
app.add_typer(seed_app, name="seed")
app.add_typer(pipeline_app, name="pipeline")
app.add_typer(macro_app, name="macro")
app.add_typer(research_app, name="research")
app.add_typer(search_app, name="search")
app.add_typer(rank_app, name="rank")
app.add_typer(demo_app, name="demo")
app.add_typer(eval_app, name="eval")

db_app = typer.Typer(help="SQLite: миграции и обслуживание.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("migrate")
def db_migrate() -> None:
    """Применить миграции SQLite (идемпотентно)."""
    from alfa_insight.db.sqlite import SqliteDB
    from alfa_insight.settings import get_settings

    settings = get_settings()
    db = SqliteDB(settings.sqlite_path)
    applied = db.migrate()
    db.close()
    typer.echo(
        f"{settings.sqlite_path}: применено миграций {len(applied)}"
        + (f" ({', '.join(applied)})" if applied else "")
    )


@app.command("init")
def init_cmd() -> None:
    """Подготовка окружения (идемпотентно, 13-deploy-demo.md §3.5): миграции, данные, seed, макро, ранжирование."""
    from alfa_insight.data.commands import build_cmd
    from alfa_insight.ingest.commands import ingest_seed, pipeline_run_cmd
    from alfa_insight.ingest.macro_commands import macro_refresh
    from alfa_insight.ingest.research.commands import research_ingest
    from alfa_insight.llm.commands import cache_import
    from alfa_insight.ranking.commands import rank_all
    from alfa_insight.settings import get_settings

    settings = get_settings()
    if settings.data_profile == "real" and not any(settings.raw_dir.glob("*.csv")):
        typer.echo(
            f"DATA_PROFILE=real, но в {settings.raw_dir} нет CSV — поставьте DATA_PROFILE=synthetic", err=True
        )
        raise typer.Exit(1)
    typer.echo("1/8 миграции")
    db_migrate()
    typer.echo("2/8 данные")
    build_cmd(force=False)
    typer.echo("3/8 кеш LLM для seed")
    cache_import(settings.seed_dir / "llm_cache_demo.jsonl")
    typer.echo("4/8 seed-новости")
    ingest_seed(shift_to_now=settings.seed_shift_to_now, path=None)
    typer.echo("5/8 разметка и кластеризация")
    pipeline_run_cmd(until="clustered", max_cost=settings.init_max_cost_rub, no_fetch=True)
    pdfs = list((settings.raw_dir / "research").glob("*.pdf"))
    typer.echo(f"6/8 аналитика Альфа-Банка: PDF {len(pdfs)}")
    if pdfs:
        research_ingest(max_cost=settings.init_max_cost_rub, vision=False, directory=None)
    typer.echo("7/8 ставка и курсы ЦБ")
    macro_refresh()
    typer.echo("8/8 ранжирование")
    rank_all()
    typer.echo("init: готово")


@app.command("worker")
def worker_cmd() -> None:
    """Фоновый планировщик: сбор, конвейер, ранжирование, прекомпьют, макро."""
    import asyncio

    from alfa_insight.worker.main import run_worker

    asyncio.run(run_worker())


@app.command("precompute")
def precompute_cmd(
    companies: str = typer.Option("demo", "--companies", help="demo | all | список company_id через запятую"),
    top_k: int | None = typer.Option(None, "--top-k", help="Событий на компанию (по умолчанию из demo.yaml)"),
    min_score: float | None = typer.Option(None, "--min-score"),
    limit: int = typer.Option(50, "--limit", help="Максимум прогонов за запуск"),
) -> None:
    """Предрасчёт инсайтов (режим pipeline) для top-K событий компаний."""
    import asyncio

    from alfa_insight.appctx import build_context
    from alfa_insight.services.jobs import JobRunner, enqueue_precompute, precompute_companies
    from alfa_insight.store.runs import RunStore

    ctx = build_context()
    runner = JobRunner(ctx)
    runner.recover_stale()
    ids = precompute_companies(ctx, companies)
    queued = enqueue_precompute(ctx, companies=ids, top_k=top_k, min_score=min_score)
    typer.echo(f"Компаний: {len(ids)}, поставлено в очередь: {queued}")
    done = asyncio.run(runner.process_queue(limit=limit))
    stats = RunStore(ctx.db).count_by_status()
    typer.echo(f"Выполнено прогонов: {done}; статусы: {stats}")


@app.command("version")
def version_cmd() -> None:
    """Версия пакета."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
