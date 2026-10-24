"""`alfa demo`: заморозка демо-содержимого для режима replay (docs/13-deploy-demo.md §6.1)."""

from __future__ import annotations

import json

import typer

demo_app = typer.Typer(help="Демо-кураторство и заморозка кеша.", no_args_is_help=True)


@demo_app.command("freeze")
def demo_freeze() -> None:
    """Выгрузить кеш разметки seed-новостей в data/seed/llm_cache_demo.jsonl и снимок ставки и курсов.

    В файл попадает только разметка публичных seed-новостей: ответы по аналитике Альфа-Банка и инсайты
    содержат выдержки из PDF кейса, которые нельзя публиковать.
    """
    from alfa_insight.appctx import build_context
    from alfa_insight.ingest.macro import write_snapshot
    from alfa_insight.ingest.tagging import render_tagging
    from alfa_insight.store.llm import LLMStore
    from alfa_insight.store.macro import MacroStore
    from alfa_insight.store.news import NewsStore

    ctx = build_context()
    news = NewsStore(ctx.db)
    wanted: dict[str, str] = {}  # текст user-сообщения → версия промпта
    for nid in ctx.db.query("SELECT id FROM news WHERE origin = 'seed' ORDER BY id"):
        row = news.get(int(nid["id"]))
        if row is None:
            continue
        version, messages = render_tagging(ctx, row)
        wanted[messages[-1].text()] = version
    rows = ctx.db.query("SELECT key, request_json FROM llm_cache WHERE task = 'tagging'")
    keys = []
    for r in rows:
        msgs = json.loads(r["request_json"]).get("messages", [])
        user = next((m["content"] for m in reversed(msgs) if m.get("role") == "user"), None)
        if isinstance(user, str) and user in wanted:
            keys.append(r["key"])
    items = LLMStore(ctx.db).cache_export(keys)
    path = ctx.settings.seed_dir / "llm_cache_demo.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for it in items:
            it["request"] = {}  # текст новостей уже есть в news.jsonl; ключ кеша считается заново не нужен
            fh.write(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n")
    typer.echo(f"{path}: записей {len(items)} из {len(wanted)} seed-новостей")
    snap = ctx.settings.seed_dir / "macro.json"
    typer.echo(f"{snap}: точек {write_snapshot(MacroStore(ctx.db), snap)}")
