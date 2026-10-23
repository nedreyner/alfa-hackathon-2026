"""CLI `alfa`: точка входа для всех операций с данными, LLM, конвейером и сервисами."""

from __future__ import annotations

import typer

from alfa_insight import __version__

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


GROUPS: dict[str, str] = {
    "data": "CSV → DuckDB, синтетика, проверка данных, профили.",
    "llm": "LLM-шлюз: probe, бюджет, кеш.",
    "ingest": "Сбор новостей: RSS, seed.",
    "pipeline": "Конвейер новостей: префильтр, разметка, кластеризация.",
    "seed": "Seed-набор новостей: сбор и кураторство.",
    "research": "Аналитика Альфа-Банка из PDF.",
    "macro": "Макроданные ЦБ.",
    "rank": "Ранжирование событий для компаний.",
    "search": "Поиск по новостям и аналитике.",
    "eval": "Офлайн-оценка качества.",
    "demo": "Демо-кураторство и заморозка кеша.",
    "api": "API: OpenAPI-схема и служебные команды.",
}

for _name, _help in GROUPS.items():
    app.add_typer(_stub_group(_name, _help), name=_name)


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
    """Подготовка окружения: миграции, данные, seed (используется в Docker)."""
    _not_implemented("init")


@app.command("worker")
def worker_cmd() -> None:
    """Фоновый планировщик: сбор, конвейер, прекомпьют."""
    _not_implemented("worker")


@app.command("precompute")
def precompute_cmd() -> None:
    """Предрасчёт инсайтов для демо-компаний."""
    _not_implemented("precompute")


@app.command("version")
def version_cmd() -> None:
    """Версия пакета."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
