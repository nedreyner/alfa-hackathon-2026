from __future__ import annotations

from datetime import UTC, datetime

from alfa_insight.agent.evidence import EvidenceRegistry


def test_dedup_and_numbering() -> None:
    reg = EvidenceRegistry()
    e1 = reg.add(source_id="news:1", kind="news", title="Пошлины", text="Пошлина вырастет до 15%.")
    e2 = reg.add(
        source_id="data:SYN-DEMO-02:supply:metallurgy",
        kind="client_data",
        title="Закупки",
        text="Металлургия — 34% закупок, 1,2 млрд руб. за год.",
    )
    again = reg.add(source_id="news:1", kind="news", title="другое", text="другой текст 99%")
    assert (e1.eid, e2.eid) == ("E1", "E2") and again is e1 and len(reg) == 2
    assert reg.get("E2") is e2 and reg.get("E3") is None and reg.get("X1") is None
    assert reg.by_source("news:1") is e1 and [e.eid for e in reg.all()] == ["E1", "E2"]
    assert e1.untrusted and not e2.untrusted
    assert 15.0 in e1.numbers and 34.0 in e2.numbers and 1.2e9 in e2.numbers
    assert reg.kind_label(e1) == "Новость" and reg.kind_label(e2) == "Ваши данные"


def test_trim_and_limits() -> None:
    reg = EvidenceRegistry(text_chars=40, max_items=2)
    long = "Ставка 14%. " + "слово " * 50 + "последнее число 77%"
    item = reg.add(
        source_id="cbr:key_rate:2026-10-22",
        kind="cbr",
        title="Ключевая ставка",
        text=long,
        published_at=datetime(2026, 10, 22, tzinfo=UTC),
        meta={"indicator": "key_rate"},
    )
    assert len(item.text) <= 46 and item.text.endswith("[…]")
    assert 14.0 in item.numbers and 77.0 not in item.numbers  # числа — из того, что видит модель
    assert not reg.full
    reg.add(source_id="alfa:x:p1:c0", kind="alfa", title="Обзор", text="Рост 3%")
    assert reg.full and reg.all()[1].untrusted
