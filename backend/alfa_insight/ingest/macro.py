"""Ключевая ставка (SOAP DailyInfo) и курсы валют (XML_dynamic) ЦБ РФ, снимок для работы без сети."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import httpx

from alfa_insight.store.macro import MacroStore
from alfa_insight.timeutil import to_iso, utc_now

SOAP_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
FX_URL = "https://www.cbr.ru/scripts/XML_dynamic.asp"
CURRENCIES = {
    "fx_usd": "R01235",
    "fx_eur": "R01239",
    "fx_cny": "R01375",
    "fx_try": "R01700J",
    "fx_aed": "R01230",
    "fx_inr": "R01270",
    "fx_kzt": "R01335",
}
FIRST_LOAD_DAYS = 180
OVERLAP_DAYS = 7


def _soap_body(start: date, end: date) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body>'
        f'<KeyRateXML xmlns="http://web.cbr.ru/"><fromDate>{start.isoformat()}</fromDate>'
        f"<ToDate>{end.isoformat()}</ToDate></KeyRateXML></soap:Body></soap:Envelope>"
    )


def parse_key_rate(xml: bytes) -> list[tuple[str, float]]:
    root = ET.fromstring(xml)
    points = []
    for kr in root.iter("KR"):
        dt = kr.findtext("DT") or ""
        rate = kr.findtext("Rate")
        if dt and rate:
            points.append((dt[:10], float(rate.replace(",", "."))))
    return sorted(points)


def parse_fx(xml: bytes) -> list[tuple[str, float]]:
    root = ET.fromstring(xml)  # кодировка windows-1251 объявлена в заголовке XML
    points = []
    for rec in root.iter("Record"):
        d = rec.get("Date") or ""
        day, month, year = d.split(".")
        vunit = rec.findtext("VunitRate")
        if vunit:
            value = float(vunit.replace(",", "."))
        else:
            nominal = float((rec.findtext("Nominal") or "1").replace(",", "."))
            value = float((rec.findtext("Value") or "0").replace(",", ".")) / nominal
        points.append((f"{year}-{month}-{day}", round(value, 6)))
    return sorted(points)


async def refresh_macro(
    store: MacroStore, *, transport: httpx.AsyncBaseTransport | None = None, today: date | None = None
) -> dict[str, int]:
    end = today or utc_now().date()
    kw: dict[str, object] = {"timeout": 20.0}
    if transport is not None:
        kw["transport"] = transport
    loaded: dict[str, int] = {}
    async with httpx.AsyncClient(**kw) as client:  # type: ignore[arg-type]

        def start_for(indicator: str) -> date:
            last = store.last_date(indicator)
            return (last - timedelta(days=OVERLAP_DAYS)) if last else end - timedelta(days=FIRST_LOAD_DAYS)

        resp = await client.post(
            SOAP_URL,
            content=_soap_body(start_for("key_rate"), end),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": '"http://web.cbr.ru/KeyRateXML"',
            },
        )
        resp.raise_for_status()
        loaded["key_rate"] = store.upsert("key_rate", parse_key_rate(resp.content))
        for indicator, code in CURRENCIES.items():
            start = start_for(indicator)
            resp = await client.get(
                FX_URL,
                params={
                    "date_req1": start.strftime("%d/%m/%Y"),
                    "date_req2": end.strftime("%d/%m/%Y"),
                    "VAL_NM_RQ": code,
                },
            )
            resp.raise_for_status()
            loaded[indicator] = store.upsert(indicator, parse_fx(resp.content))
    return loaded


def write_snapshot(store: MacroStore, path: Path) -> int:
    series = {ind: [[d.isoformat(), v] for d, v, _ in store.series(ind)] for ind in store.indicators()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"generated_at": to_iso(utc_now()), "series": series}, ensure_ascii=False, indent=0),
        encoding="utf-8",
    )
    return sum(len(v) for v in series.values())


def load_snapshot(store: MacroStore, path: Path, *, only_if_empty: bool = True) -> int:
    if not path.exists() or (only_if_empty and store.count() > 0):
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        store.upsert(ind, [(d, float(v)) for d, v in points], source="snapshot")
        for ind, points in data["series"].items()
    )
