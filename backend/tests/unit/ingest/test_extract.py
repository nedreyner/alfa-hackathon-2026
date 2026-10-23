from __future__ import annotations

from pathlib import Path

import pytest

from alfa_insight.ingest.extract import choose_body, content_hash, extract_main_text

HTML = Path(__file__).resolve().parents[2] / "fixtures" / "html"
BOILERPLATE = ["Читайте также", "Подписывайтесь", "Фото:", "Реклама", "Новости партнеров"]


@pytest.mark.parametrize("name", ["interfax.html", "tass.html", "cbr.html"])
def test_extract_article(name: str) -> None:
    html = (HTML / name).read_text(encoding="utf-8")
    res = choose_body(html, "https://example.ru/a", "заголовок", None, BOILERPLATE)
    assert res.body_source == "full" and len(res.body) > 300
    assert len(extract_main_text(html) or "") > 300
    for junk in (
        "Главная",
        "Спорт",
        "Купите квартиру",
        "Все права защищены",
        "Футбольный матч",
        "Подписывайтесь",
    ):
        assert junk not in res.body, junk
    assert res.title


def test_fallbacks() -> None:
    short = "<html><body><p>Коротко.</p></body></html>"
    res = choose_body(short, None, "Заголовок", "Анонс новости из RSS", BOILERPLATE)
    assert (res.body, res.body_source) == ("Анонс новости из RSS", "rss_summary")
    assert choose_body(None, None, "Только заголовок", None, BOILERPLATE).body == "Только заголовок"
    assert content_hash("A", "B") == content_hash("a", "b")
