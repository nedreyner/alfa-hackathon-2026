from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from alfa_insight.db.sqlite import SqliteDB
from alfa_insight.ingest.macro import load_snapshot, parse_fx, parse_key_rate, refresh_macro, write_snapshot
from alfa_insight.store.macro import MacroStore

CBR = Path(__file__).resolve().parents[2] / "fixtures" / "cbr"


def test_parse_fixtures() -> None:
    kr = parse_key_rate((CBR / "keyrate.xml").read_bytes())
    assert kr[-1] == ("2026-09-18", 14.0) and all(v == 14.0 for _, v in kr)
    inr = parse_fx((CBR / "inr.xml").read_bytes())
    assert inr[0] == ("2026-10-01", 0.870557)  # за 1 рупию, а не за 100
    try_ = parse_fx((CBR / "try.xml").read_bytes())
    no_vunit = parse_fx((CBR / "try_no_vunit.xml").read_bytes())
    assert try_[0] == ("2026-10-01", 1.70677) and no_vunit[0] == ("2026-10-01", 1.70677)  # Value / Nominal


async def test_refresh_and_snapshot(tmp_path: Path) -> None:
    db = SqliteDB(tmp_path / "a.sqlite")
    db.migrate()
    store = MacroStore(db)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(200, content=(CBR / "keyrate.xml").read_bytes())
        name = "inr.xml" if req.url.params["VAL_NM_RQ"] == "R01270" else "try.xml"
        return httpx.Response(200, content=(CBR / name).read_bytes())

    loaded = await refresh_macro(store, transport=httpx.MockTransport(handler), today=date(2026, 10, 6))
    assert loaded["key_rate"] > 5 and loaded["fx_inr"] == 4
    s = store.summary("key_rate")
    assert s and s.latest.value == 14.0 and s.unit == "%" and s.source == "cbr"
    snap = tmp_path / "macro.json"
    assert write_snapshot(store, snap) > 10
    db2 = SqliteDB(tmp_path / "b.sqlite")
    db2.migrate()
    store2 = MacroStore(db2)
    assert load_snapshot(store2, snap) > 10
    s2 = store2.summary("fx_inr")
    assert s2 and s2.source == "snapshot" and s2.latest.value < 1
    assert load_snapshot(store2, snap) == 0  # таблица уже не пуста
