"""CLI `alfa llm …`: бюджет, кеш (probe — в T1.10)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import typer

from alfa_insight.settings import Settings
from alfa_insight.store.llm import LLMStore

llm_app = typer.Typer(help="LLM-шлюз: probe, бюджет, кеш.", no_args_is_help=True)
cache_app = typer.Typer(help="Кеш LLM-ответов.", no_args_is_help=True)
llm_app.add_typer(cache_app, name="cache")


def _store() -> tuple[LLMStore, Settings]:
    from alfa_insight.db.sqlite import open_db
    from alfa_insight.settings import get_settings
    from alfa_insight.store.llm import LLMStore

    settings = get_settings()
    return LLMStore(open_db(settings.sqlite_path)), settings


@llm_app.command("budget")
def budget_cmd() -> None:
    """Траты сегодня и за 7 дней по задачам и моделям, остаток и режим бюджета."""
    from alfa_insight.llm.budget import BudgetGuard
    from alfa_insight.timeutil import budget_day

    store, settings = _store()
    guard = BudgetGuard(
        store,
        daily_limit_rub=settings.llm_daily_budget_rub,
        interactive_reserve_rub=settings.llm_interactive_reserve_rub,
        max_run_cost_rub=settings.llm_max_run_cost_rub,
        tz=settings.budget_tz,
    )
    today = budget_day(tz=settings.budget_tz)
    typer.echo(
        f"Сегодня ({today}): потрачено {guard.spent():.2f} ₽ из {guard.limit:.0f} ₽, "
        f"остаток {guard.remaining():.2f} ₽, резерв под интерактив {guard.reserve:.0f} ₽, режим {guard.mode()}"
    )
    rows = store.spend_by((today - timedelta(days=6)).isoformat())
    if not rows:
        typer.echo("Вызовов за 7 дней нет")
        return
    typer.echo(f"{'день':10}  {'задача':20}  {'модель':10}  вызовы  кеш  вход     выход    ₽")
    for r in rows:
        typer.echo(
            f"{r['budget_day']:10}  {r['task']:20}  {r['model']:10}  {r['calls']:6}  {r['cached'] or 0:3}  "
            f"{r['tokens_in'] or 0:7}  {r['tokens_out'] or 0:7}  {r['cost_rub'] or 0:.4f}"
        )


@cache_app.command("stats")
def cache_stats() -> None:
    """Записи кеша по задачам."""
    store, _ = _store()
    stats = store.cache_stats()
    if not stats:
        typer.echo("Кеш пуст")
    for s in stats:
        typer.echo(
            f"{s['task']:20} записей {s['entries']:5}  попаданий {s['hits'] or 0:5}  {s['cost_rub'] or 0:.4f} ₽"
        )


@cache_app.command("clear")
def cache_clear(task: str | None = typer.Option(None, "--task", help="Только для задачи")) -> None:
    """Очистить кеш (целиком или по задаче)."""
    store, _ = _store()
    typer.echo(f"Удалено записей: {store.cache_clear(task)}")


@cache_app.command("export")
def cache_export(
    out: Path = typer.Option(..., "--out", help="Файл JSONL"),
    runs: str | None = typer.Option(None, "--runs", help="id прогонов через запятую (по умолчанию весь кеш)"),
) -> None:
    """Выгрузить кеш в JSONL (весь или записи указанных прогонов)."""
    store, _ = _store()
    keys = store.run_cache_keys([r.strip() for r in runs.split(",") if r.strip()]) if runs else None
    items = store.cache_export(keys)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n")
    typer.echo(f"{out}: записей {len(items)}")


@cache_app.command("import")
def cache_import(path: Path = typer.Argument(..., help="Файл JSONL")) -> None:
    """Загрузить кеш из JSONL (существующие ключи не перезаписываются)."""
    store, _ = _store()
    if not path.exists():
        typer.echo(f"{path}: файла нет, импорт пропущен")
        return
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    typer.echo(f"{path}: загружено {store.cache_import(items)} из {len(items)}")
