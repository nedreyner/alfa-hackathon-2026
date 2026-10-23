from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.ingest.rss import collect_rss, parse_feed
from alfa_insight.ingest.sources import SourcesConfig, load_sources
from alfa_insight.store.kv import KVStore
from alfa_insight.store.news import NewsStore

RSS = Path(__file__).resolve().parents[2] / "fixtures" / "rss"
ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.fixture
def sources() -> SourcesConfig:
    return load_sources(ROOT / "config")


def test_parse_tass(sources: SourcesConfig) -> None:
    src = sources.get("tass")
    assert src is not None
    items = parse_feed(src, (RSS / "tass.xml").read_bytes(), now=NOW, max_age_days=7)
    assert [i.title for i in items] == [
        "Минпромторг предложил повысить пошлины на арматуру",
        "Сборная сыграла вничью",
    ]
    first = items[0]
    assert first.url == "https://tass.ru/ekonomika/100001"
    assert first.published_at == "2026-10-22T09:30:00Z"
    assert first.rss_categories == ["Экономика и бизнес"]
    assert first.rss_summary == "Ведомство предлагает поднять ввозную пошлину до 15%."
    assert first.trust == 0.9 and first.publisher == "ТАСС"


def test_parse_cp1251_and_empty_description(sources: SourcesConfig) -> None:
    ifx = sources.get("interfax")
    cbr = sources.get("cbr_events")
    assert ifx and cbr
    items = parse_feed(ifx, (RSS / "interfax.xml").read_bytes(), now=NOW, max_age_days=7)
    assert items[0].url == "https://www.interfax.ru/business/200001"
    assert items[1].url == "https://www.interfax.ru/business/200002" and items[1].rss_summary is None
    assert items[0].external_id == "https://www.interfax.ru/business/200001"
    c = parse_feed(cbr, (RSS / "cbr.xml").read_bytes(), now=NOW, max_age_days=7)
    assert c[0].rss_summary is None and c[0].trust == 1.0


async def test_collect_idempotent_and_isolated_failures(tmp_path: Path, sources: SourcesConfig) -> None:
    db = SqliteDB(tmp_path / "app.sqlite")
    db.migrate()
    news, kv = NewsStore(db), KVStore(db)
    files = {"tass.ru": "tass.xml", "www.interfax.ru": "interfax.xml", "www.cbr.ru": "cbr.xml"}

    def handler(req: httpx.Request) -> httpx.Response:
        name = files.get(req.url.host)
        if name is None:
            return httpx.Response(500)
        return httpx.Response(200, content=(RSS / name).read_bytes(), headers={"etag": f'"{name}"'})

    transport = httpx.MockTransport(handler)
    res = await collect_rss(sources, news, kv, transport=transport, now=NOW)
    by_id = {r.source_id: r for r in res}
    assert by_id["tass"].items_new == 2 and by_id["interfax"].items_new == 2
    assert by_id["cbr_events"].ok and not by_id["kommersant"].ok  # 500 у одного не мешает остальным
    assert "rbc" not in by_id  # geo: ru пропущен при INGEST_GEO=any
    total = db.scalar("SELECT count(*) FROM news")
    res2 = await collect_rss(sources, news, kv, transport=transport, now=NOW)
    assert db.scalar("SELECT count(*) FROM news") == total
    assert all(r.items_new == 0 for r in res2 if r.ok)
    status = kv.get("source_status:tass")
    assert status["ok"] and status["items_total"] == 2
    assert kv.get("source_status:kommersant")["ok"] is False
    assert kv.get("rss_etag:tass") == {"etag": '"tass.xml"'}
    row = news.by_url("https://tass.ru/ekonomika/100001")
    assert row is not None and row.status == "new" and row.origin == "rss"
