"""Собирает THIRD_PARTY_NOTICES.md: ручные разделы + автоматические списки зависимостей.

Запуск: `make notices` (рантайм-зависимости Python — без dev-группы, JS — только production).
Аргументы: путь к markdown от pip-licenses и к JSON от license-checker.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = """# Сторонние компоненты и данные

«Альфа Инсайт» распространяется по лицензии MIT (`LICENSE`). Ниже — компоненты и данные третьих сторон.
Файл собирается командой `make notices`; разделы 1–5 пишутся вручную, разделы 6–7 — автоматически.

## 1. Дизайн-система Альфа-Банка

`@alfalab/core-components`, `@alfalab/icons-glyph`, `@alfalab/icons-logotype` — MIT, © АО «Альфа-Банк»
(https://github.com/core-ds/core-components). Используются для интерфейса в стиле Альфа-Банка.
Транзитивные пакеты `react-canvas-pattern-lock` и `@alfalab/react-canvas-pattern-lock` не объявляют лицензию;
компонент графического ключа в приложении не используется и в сборку `frontend/dist` не попадает
(проверено поиском по сборке).

## 2. Языковые модели

Все вызовы LLM идут через шлюз хакатона «Альфа-Будущее» к моделям из разрешённого списка организаторов:
Gemma 4 26B (Google), Qwen3.6-35B и Qwen3-VL-30B (Alibaba), DeepSeek-V4.1-Flash (DeepSeek),
GLM-5.3-Flash (Zhipu AI), Kimi K2.6 (Moonshot AI). Веса моделей в репозитории не хранятся; условия
использования определяют их правообладатели и организаторы. Ключ шлюза в репозиторий и браузер не попадает.

## 3. Тексты новостей

Заголовки и тексты в `data/seed/news.jsonl` и в базе принадлежат их правообладателям (Интерфакс, ТАСС,
Коммерсантъ, Ведомости, РБК, ПРАЙМ, Банк России и др.). Хранятся фрагменты до 3000 символов со ссылкой на
первоисточник — только для демонстрации прототипа. В интерфейсе у каждого факта есть ссылка на источник.
Кеш разметки `data/seed/llm_cache_demo.jsonl` содержит ответы моделей по этим новостям.

## 4. Данные Банка России

Ключевая ставка и официальные курсы валют (`data/seed/macro.json`, `ingest/macro`) — с сайта Банка России
(https://cbr.ru), с указанием источника.

## 5. Данные кейса

CSV с данными компаний и платежей и PDF аналитики Альфа-Банка предоставлены организаторами только для
хакатона и **не публикуются**: каталог `data/raw/` в `.gitignore`, выдержки из PDF не попадают ни в кеш
`llm_cache_demo.jsonl`, ни в отчёты оценки. В репозитории — синтетические данные (`data/synthetic/`,
генератор `alfa data synth`), созданные командой.
"""


def js_section(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for key, v in sorted(data.items()):
        if key.startswith("alfa-insight-web@"):
            continue
        name, _, version = key.rpartition("@")
        lic = v.get("licenses")
        lic = " OR ".join(lic) if isinstance(lic, list) else str(lic)
        if lic.startswith("Custom"):
            lic = "не указана (см. раздел 1)"
        rows.append(f"| {name} | {version} | {lic} | {v.get('repository', '')} |")
    head = "| Пакет | Версия | Лицензия | Репозиторий |\n|---|---|---|---|"
    return f"## 7. JavaScript (production, `npx license-checker --production`)\n\n{head}\n" + "\n".join(rows) + "\n"


def main() -> None:
    py_md, js_json = Path(sys.argv[1]), Path(sys.argv[2])
    py = py_md.read_text(encoding="utf-8").strip()
    text = (
        MANUAL
        + "\n## 6. Python (рантайм, `pip-licenses --with-urls`)\n\n"
        + "`tld` распространяется по выбору MPL-1.1 / GPL-2.0 / LGPL-2.1+; используется на условиях MPL-1.1.\n\n"
        + py
        + "\n\n"
        + js_section(js_json)
    )
    (ROOT / "THIRD_PARTY_NOTICES.md").write_text(text, encoding="utf-8")
    print(f"THIRD_PARTY_NOTICES.md: Python {py.count(chr(10)) - 1} пакетов, JS {js_section(js_json).count(chr(10)) - 4} пакетов")


if __name__ == "__main__":
    main()
