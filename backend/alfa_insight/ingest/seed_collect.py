"""`alfa seed collect`: RSS → полный текст → префильтр без LLM → дописать в seed JSONL.

Сбор идёт в отдельной базе `data/runtime/seed_collect.sqlite`, чтобы не смешивать RSS-записи с рабочей
базой (иначе `ingest seed` пропустил бы те же URL как дубли).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from alfa_insight.appctx import AppContext
from alfa_insight.config_models import load_yaml
from alfa_insight.db.sqlite import open_db
from alfa_insight.ingest.pipeline import stage_extract, stage_prefilter_dedup
from alfa_insight.ingest.rss import collect_rss
from alfa_insight.ingest.seed import read_seed, seed_item_from_row, write_seed
from alfa_insight.ingest.sources import SourcesConfig
from alfa_insight.store.kv import KVStore
from alfa_insight.store.news import NewsStore


async def collect_seed(
    ctx: AppContext,
    out: Path,
    *,
    max_items: int = 400,
    extra_feeds: Path | None = None,
    max_age_days: int = 45,
) -> dict[str, int]:
    db = open_db(ctx.settings.runtime_dir / "seed_collect.sqlite")
    ctx = replace(ctx, db=db, kv=KVStore(db), _lazy={})
    store = NewsStore(ctx.db)
    feeds: list[SourcesConfig] = [ctx.sources]
    if extra_feeds is not None:
        feeds.append(load_yaml(extra_feeds, SourcesConfig))
    for cfg in feeds:
        await collect_rss(cfg, store, ctx.kv, ingest_geo=ctx.settings.ingest_geo, max_age_days=max_age_days)
    while True:
        stats = await stage_extract(ctx, max_extract=100)
        if stats.extracted == 0:
            break
    survivors, _ = stage_prefilter_dedup(ctx, store.by_status("extracted", 5000))
    existing = read_seed(out)
    known = {i.url for i in existing if i.url}
    added = 0
    for row in sorted(survivors, key=lambda r: r.published_at):
        if added >= max_items or not row.url or row.url in known or row.origin != "rss":
            continue
        day = row.published_at[:10].replace("-", "")
        existing.append(seed_item_from_row(row, f"s-{day}-{row.id:05d}"))
        known.add(row.url)
        added += 1
    write_seed(out, existing)
    return {"before": len(existing) - added, "added": added, "passed": len(survivors)}
