# Сторонние компоненты и данные

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

## 6. Python (рантайм, `pip-licenses --with-urls`)

`tld` распространяется по выбору MPL-1.1 / GPL-2.0 / LGPL-2.1+; используется на условиях MPL-1.1.

| Name               | Version            | License                                       | URL                                                                                |
|--------------------|--------------------|-----------------------------------------------|------------------------------------------------------------------------------------|
| python-dateutil    | 3.0.0              | Apache Software License; BSD License          | https://github.com/dateutil/dateutil                                               |
| sniffio            | 1.3.1              | Apache Software License; MIT License          | https://github.com/python-trio/sniffio                                             |
| uvloop             | 0.23.0             | Apache Software License; MIT License          | UNKNOWN                                                                            |
| courlan            | 1.4.0              | Apache-2.0                                    | https://github.com/adbar/courlan                                                   |
| htmldate           | 1.11.0             | Apache-2.0                                    | https://htmldate.readthedocs.io                                                    |
| openai             | 3.37.0             | Apache-2.0                                    | https://github.com/openai/openai-python                                            |
| opentelemetry-api  | 1.45.1             | Apache-2.0                                    | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api |
| trafilatura        | 2.3.1              | Apache-2.0                                    | https://trafilatura.readthedocs.io                                                 |
| tzdata             | 2026.5             | Apache-2.0                                    | https://github.com/python/tzdata                                                   |
| regex              | 2026.9.29          | Apache-2.0 AND CNRI-Python                    | https://github.com/mrabarnett/mrab-regex                                           |
| cryptography       | 50.0.2             | Apache-2.0 OR BSD-3-Clause                    | https://github.com/pyca/cryptography                                               |
| Jinja2             | 3.1.6              | BSD License                                   | https://github.com/pallets/jinja/                                                  |
| babel              | 2.18.0             | BSD License                                   | https://babel.pocoo.org/                                                           |
| httpx              | 0.28.1             | BSD License                                   | https://github.com/encode/httpx                                                    |
| itsdangerous       | 2.2.0              | BSD License                                   | https://github.com/pallets/itsdangerous/                                           |
| jusText            | 3.0.2              | BSD License                                   | https://github.com/miso-belica/jusText                                             |
| Pygments           | 2.21.0             | BSD-2-Clause                                  | https://pygments.org                                                               |
| feedparser         | 6.0.14             | BSD-2-Clause                                  | https://github.com/kurtmckee/feedparser                                            |
| MarkupSafe         | 3.0.4              | BSD-3-Clause                                  | https://github.com/pallets/markupsafe/                                             |
| click              | 8.5.0              | BSD-3-Clause                                  | https://github.com/pallets/click/                                                  |
| dateparser         | 1.4.3              | BSD-3-Clause                                  | https://github.com/scrapinghub/dateparser                                          |
| httpcore           | 1.0.9              | BSD-3-Clause                                  | https://www.encode.io/httpcore/                                                    |
| httpcore2          | 2.16.0             | BSD-3-Clause                                  | https://github.com/pydantic/httpx2                                                 |
| httpx2             | 2.16.0             | BSD-3-Clause                                  | https://github.com/pydantic/httpx2                                                 |
| idna               | 3.20               | BSD-3-Clause                                  | https://github.com/kjd/idna                                                        |
| lxml               | 6.1.3              | BSD-3-Clause                                  | https://lxml.de/                                                                   |
| lxml_html_clean    | 0.4.5              | BSD-3-Clause                                  | https://github.com/fedora-python/lxml_html_clean/                                  |
| pycparser          | 3.12               | BSD-3-Clause                                  | https://github.com/eliben/pycparser                                                |
| python-dotenv      | 1.2.4              | BSD-3-Clause                                  | https://github.com/theskumar/python-dotenv                                         |
| sse-starlette      | 3.5.0              | BSD-3-Clause                                  | https://github.com/sysid/sse-starlette                                             |
| starlette          | 1.9.0              | BSD-3-Clause                                  | https://github.com/Kludex/starlette                                                |
| uvicorn            | 0.54.0             | BSD-3-Clause                                  | https://uvicorn.dev/                                                               |
| websockets         | 17.3               | BSD-3-Clause                                  | https://github.com/python-websockets/websockets                                    |
| pypdfium2          | 5.14.0             | BSD-3-Clause, Apache-2.0, dependency licenses | https://github.com/pypdfium2-team/pypdfium2                                        |
| shellingham        | 1.5.4              | ISC License (ISCL)                            | https://github.com/sarugaku/shellingham                                            |
| annotated-doc      | 0.0.5              | MIT                                           | https://github.com/fastapi/annotated-doc                                           |
| annotated-types    | 0.8.0              | MIT                                           | https://github.com/annotated-types/annotated-types                                 |
| anyio              | 4.15.1             | MIT                                           | https://anyio.readthedocs.io/en/stable/versionhistory.html                         |
| charset-normalizer | 3.5.2              | MIT                                           | https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md               |
| fastapi            | 0.162.0            | MIT                                           | https://github.com/fastapi/fastapi                                                 |
| httptools          | 0.9.0              | MIT                                           | https://github.com/MagicStack/httptools                                            |
| jiter              | 0.18.0             | MIT                                           | https://github.com/pydantic/jiter/                                                 |
| pdfminer.six       | 20260107           | MIT                                           | https://github.com/pdfminer/pdfminer.six                                           |
| pydantic           | 2.14.1             | MIT                                           | https://github.com/pydantic/pydantic                                               |
| pydantic-settings  | 2.16.1             | MIT                                           | https://github.com/pydantic/pydantic-settings                                      |
| pydantic_core      | 2.50.1             | MIT                                           | https://github.com/pydantic                                                        |
| truststore         | 0.10.5             | MIT                                           | https://github.com/sethmlarson/truststore                                          |
| typer              | 0.27.3             | MIT                                           | https://github.com/fastapi/typer                                                   |
| typing-inspection  | 0.4.4              | MIT                                           | https://github.com/pydantic/typing-inspection                                      |
| tzlocal            | 5.4.5              | MIT                                           | https://github.com/regebro/tzlocal/blob/master/CHANGES.txt                         |
| urllib3            | 2.8.0              | MIT                                           | https://github.com/urllib3/urllib3/blob/main/CHANGES.rst                           |
| APScheduler        | 3.11.3             | MIT License                                   | https://apscheduler.readthedocs.io/en/3.x/versionhistory.html                      |
| DAWG2-Python       | 0.9.0              | MIT License                                   | https://github.com/pymorphy2-fork/DAWG-Python/                                     |
| PyYAML             | 6.0.3              | MIT License                                   | https://pyyaml.org/                                                                |
| duckdb             | 2.0.0              | MIT License                                   | https://github.com/duckdb/duckdb-python                                            |
| h11                | 0.16.0             | MIT License                                   | https://github.com/python-hyper/h11                                                |
| markdown-it-py     | 4.2.0              | MIT License                                   | https://github.com/executablebooks/markdown-it-py                                  |
| mdurl              | 0.1.2              | MIT License                                   | https://github.com/executablebooks/mdurl                                           |
| pdfplumber         | 0.11.10            | MIT License                                   | https://github.com/jsvine/pdfplumber                                               |
| pymorphy3          | 2.0.6              | MIT License                                   | https://github.com/no-plagiarism/pymorphy3                                         |
| pymorphy3-dicts-ru | 2.4.417150.4580142 | MIT License                                   | https://github.com/no-plagiarism/pymorphy3-dicts                                   |
| pytz               | 2026.5             | MIT License                                   | http://pythonhosted.org/pytz                                                       |
| rich               | 15.0.0             | MIT License                                   | https://github.com/Textualize/rich                                                 |
| six                | 1.17.0             | MIT License                                   | https://github.com/benjaminp/six                                                   |
| watchfiles         | 1.3.0              | MIT License                                   | https://github.com/samuelcolvin/watchfiles                                         |
| structlog          | 26.1.0             | MIT OR Apache-2.0                             | https://github.com/hynek/structlog/blob/main/CHANGELOG.md                          |
| cffi               | 2.1.1              | MIT-0                                         | https://cffi.readthedocs.io/en/latest/whatsnew.html                                |
| pillow             | 13.0.0             | MIT-CMU                                       | https://python-pillow.org                                                          |
| tld                | 0.13.2             | MPL-1.1 OR GPL-2.0-only OR LGPL-2.1-or-later  | https://tld.readthedocs.io/en/latest/changelog.html                                |
| orjson             | 3.13.0             | MPL-2.0 AND (Apache-2.0 OR MIT)               | https://github.com/ijl/orjson                                                      |
| certifi            | 2026.10.23         | Mozilla Public License 2.0 (MPL 2.0)          | https://github.com/certifi/python-certifi                                          |
| feedparser-sgmllib | 2.1.0              | PSF-2.0                                       | https://github.com/python-syndication/feedparser-sgmllib                           |
| typing_extensions  | 4.16.0             | PSF-2.0                                       | https://github.com/python/typing_extensions                                        |

## 7. JavaScript (production, `npx license-checker --production`)

| Пакет | Версия | Лицензия | Репозиторий |
|---|---|---|---|
| @alfalab/core-components-accordion | 3.0.13 | MIT |  |
| @alfalab/core-components-action-button | 3.0.9 | MIT |  |
| @alfalab/core-components-alert | 6.0.12 | MIT |  |
| @alfalab/core-components-amount-input | 9.4.0 | MIT |  |
| @alfalab/core-components-amount | 5.1.1 | MIT |  |
| @alfalab/core-components-attach | 8.0.12 | MIT |  |
| @alfalab/core-components-backdrop | 5.0.2 | MIT |  |
| @alfalab/core-components-badge | 7.0.3 | MIT |  |
| @alfalab/core-components-bank-card | 7.0.17 | MIT |  |
| @alfalab/core-components-base-modal | 7.2.2 | MIT |  |
| @alfalab/core-components-bottom-sheet | 8.1.16 | MIT |  |
| @alfalab/core-components-button | 13.2.4 | MIT |  |
| @alfalab/core-components-calendar-input | 12.0.22 | MIT |  |
| @alfalab/core-components-calendar-range | 9.1.8 | MIT |  |
| @alfalab/core-components-calendar-with-skeleton | 7.0.20 | MIT |  |
| @alfalab/core-components-calendar | 9.1.16 | MIT |  |
| @alfalab/core-components-card-image | 5.0.3 | MIT |  |
| @alfalab/core-components-carousel | 1.1.6 | MIT |  |
| @alfalab/core-components-cdn-icon | 7.1.9 | ISC |  |
| @alfalab/core-components-chart | 5.0.13 | MIT |  |
| @alfalab/core-components-checkbox-group | 6.0.10 | MIT |  |
| @alfalab/core-components-checkbox | 6.3.2 | MIT |  |
| @alfalab/core-components-circular-progress-bar | 5.0.13 | MIT |  |
| @alfalab/core-components-code-input | 5.1.5 | MIT |  |
| @alfalab/core-components-collapse | 6.0.3 | MIT |  |
| @alfalab/core-components-comment | 4.0.13 | MIT |  |
| @alfalab/core-components-config | 1.1.0 | MIT |  |
| @alfalab/core-components-confirmation-v1 | 3.0.12 | MIT |  |
| @alfalab/core-components-confirmation | 15.2.5 | MIT |  |
| @alfalab/core-components-custom-button | 5.0.13 | MIT |  |
| @alfalab/core-components-custom-picker-button | 4.1.24 | MIT |  |
| @alfalab/core-components-date-input | 6.0.15 | MIT |  |
| @alfalab/core-components-date-range-input | 5.0.22 | MIT |  |
| @alfalab/core-components-date-time-input | 6.0.22 | MIT |  |
| @alfalab/core-components-divider | 5.0.2 | MIT |  |
| @alfalab/core-components-drawer | 7.0.13 | MIT |  |
| @alfalab/core-components-dropzone | 6.0.2 | MIT |  |
| @alfalab/core-components-file-upload-item-v1 | 3.0.12 | MIT |  |
| @alfalab/core-components-file-upload-item | 8.2.4 | MIT |  |
| @alfalab/core-components-filter-tag | 7.1.3 | MIT |  |
| @alfalab/core-components-form-control | 14.0.11 | MIT |  |
| @alfalab/core-components-gallery | 7.4.4 | MIT |  |
| @alfalab/core-components-gap | 3.0.2 | MIT |  |
| @alfalab/core-components-generic-wrapper | 3.0.2 | MIT |  |
| @alfalab/core-components-global-store | 4.0.1 | MIT |  |
| @alfalab/core-components-grid | 5.0.2 | MIT |  |
| @alfalab/core-components-hatching-progress-bar | 4.0.1 | MIT |  |
| @alfalab/core-components-icon-button | 8.0.12 | MIT |  |
| @alfalab/core-components-icon-view | 5.0.4 | MIT |  |
| @alfalab/core-components-indicator | 4.0.2 | MIT |  |
| @alfalab/core-components-input-autocomplete | 14.0.29 | MIT |  |
| @alfalab/core-components-input | 17.2.2 | MIT |  |
| @alfalab/core-components-international-phone-input | 4.0.29 | MIT |  |
| @alfalab/core-components-intl-phone-input | 11.0.29 | MIT |  |
| @alfalab/core-components-keyboard-focusable | 6.0.2 | MIT |  |
| @alfalab/core-components-link | 7.0.3 | MIT |  |
| @alfalab/core-components-list-header | 5.0.13 | MIT |  |
| @alfalab/core-components-list | 5.0.14 | MIT |  |
| @alfalab/core-components-loader | 5.0.2 | MIT |  |
| @alfalab/core-components-lottie | 1.1.0 | MIT |  |
| @alfalab/core-components-markdown | 3.1.0 | MIT |  |
| @alfalab/core-components-masked-input | 8.0.16 | MIT |  |
| @alfalab/core-components-modal | 11.0.19 | MIT |  |
| @alfalab/core-components-mq | 6.0.9 | MIT |  |
| @alfalab/core-components-navigation-bar-private | 2.0.16 | MIT |  |
| @alfalab/core-components-navigation-bar | 3.0.15 | MIT |  |
| @alfalab/core-components-notification-manager | 7.0.13 | MIT |  |
| @alfalab/core-components-notification | 9.0.13 | MIT |  |
| @alfalab/core-components-number-input | 4.0.15 | MIT |  |
| @alfalab/core-components-page-indicator | 3.0.9 | MIT |  |
| @alfalab/core-components-pagination | 4.0.12 | MIT |  |
| @alfalab/core-components-pass-code-v1 | 3.0.12 | MIT |  |
| @alfalab/core-components-pass-code | 4.0.13 | MIT |  |
| @alfalab/core-components-password-input | 7.0.15 | MIT |  |
| @alfalab/core-components-pattern-lock-v1 | 3.0.12 | MIT |  |
| @alfalab/core-components-pattern-lock | 4.0.12 | MIT |  |
| @alfalab/core-components-phone-input | 9.0.17 | MIT |  |
| @alfalab/core-components-picker-button | 13.1.7 | MIT |  |
| @alfalab/core-components-plate | 9.0.12 | MIT |  |
| @alfalab/core-components-popover | 8.1.4 | MIT |  |
| @alfalab/core-components-popup-sheet | 3.0.19 | MIT |  |
| @alfalab/core-components-portal | 5.0.6 | MIT |  |
| @alfalab/core-components-product-cover | 3.3.0 | MIT |  |
| @alfalab/core-components-progress-bar | 5.0.2 | MIT |  |
| @alfalab/core-components-pure-cell | 6.1.0 | MIT |  |
| @alfalab/core-components-radio-group | 6.0.10 | MIT |  |
| @alfalab/core-components-radio | 6.1.2 | MIT |  |
| @alfalab/core-components-scrollbar-private | 0.0.1 | MIT |  |
| @alfalab/core-components-scrollbar | 5.0.8 | MIT |  |
| @alfalab/core-components-segmented-control | 3.1.6 | MIT |  |
| @alfalab/core-components-select-with-tags | 10.1.24 | MIT |  |
| @alfalab/core-components-select | 19.2.11 | MIT |  |
| @alfalab/core-components-shared | 2.3.0 | MIT |  |
| @alfalab/core-components-side-panel | 7.1.4 | MIT |  |
| @alfalab/core-components-skeleton | 7.0.5 | MIT |  |
| @alfalab/core-components-slider-input | 11.1.10 | MIT |  |
| @alfalab/core-components-slider | 6.1.1 | MIT |  |
| @alfalab/core-components-sortable-list | 3.0.10 | MIT |  |
| @alfalab/core-components-space | 5.0.2 | MIT |  |
| @alfalab/core-components-spinner | 6.0.9 | MIT |  |
| @alfalab/core-components-stack-context | 1.0.1 | MIT |  |
| @alfalab/core-components-stack | 7.0.1 | MIT |  |
| @alfalab/core-components-status-badge | 3.0.2 | MIT |  |
| @alfalab/core-components-status | 5.1.1 | MIT |  |
| @alfalab/core-components-stepped-progress-bar | 4.0.13 | MIT |  |
| @alfalab/core-components-steps | 3.0.11 | MIT |  |
| @alfalab/core-components-switch | 6.2.3 | MIT |  |
| @alfalab/core-components-system-message | 4.0.10 | MIT |  |
| @alfalab/core-components-tab-bar | 4.0.14 | MIT |  |
| @alfalab/core-components-table | 4.0.30 | MIT |  |
| @alfalab/core-components-tabs | 10.1.4 | MIT |  |
| @alfalab/core-components-tag | 10.3.2 | MIT |  |
| @alfalab/core-components-text | 3.0.3 | MIT |  |
| @alfalab/core-components-textarea | 10.1.4 | MIT |  |
| @alfalab/core-components-themes | 15.2.1 | MIT |  |
| @alfalab/core-components-time-input | 4.0.15 | MIT |  |
| @alfalab/core-components-toast-plate | 9.1.8 | MIT |  |
| @alfalab/core-components-toast | 8.0.15 | MIT |  |
| @alfalab/core-components-tooltip | 9.0.22 | MIT |  |
| @alfalab/core-components-types | 2.1.0 | MIT |  |
| @alfalab/core-components-typography | 6.0.13 | MIT |  |
| @alfalab/core-components-underlay | 3.2.0 | MIT |  |
| @alfalab/core-components-universal-date-input | 4.0.22 | MIT |  |
| @alfalab/core-components-universal-modal | 3.2.8 | MIT |  |
| @alfalab/core-components-vars | 11.4.1 | MIT |  |
| @alfalab/core-components-with-suffix | 6.0.16 | MIT |  |
| @alfalab/core-components | 50.38.0 | MIT |  |
| @alfalab/data | 1.10.2 | MIT |  |
| @alfalab/hooks | 1.18.1 | MIT |  |
| @alfalab/icons-glyph-26 | 1.32.2 | MIT | https://github.com/core-ds/ui-primitives |
| @alfalab/icons-glyph | 2.293.3 | MIT | https://github.com/core-ds/ui-primitives |
| @alfalab/icons-logotype | 2.37.3 | MIT | https://github.com/core-ds/ui-primitives |
| @alfalab/react-canvas-pattern-lock | 2.0.8 | не указана (см. раздел 1) | https://github.com/core-ds/react-canvas-pattern-lock |
| @alfalab/utils | 1.22.0 | MIT |  |
| @babel/runtime | 7.29.10 | MIT | https://github.com/babel/babel |
| @dnd-kit/accessibility | 3.1.1 | MIT | https://github.com/clauderic/dnd-kit |
| @dnd-kit/core | 6.3.1 | MIT | https://github.com/clauderic/dnd-kit |
| @dnd-kit/sortable | 7.0.2 | MIT | https://github.com/clauderic/dnd-kit |
| @dnd-kit/utilities | 3.2.2 | MIT | https://github.com/clauderic/dnd-kit |
| @juggle/resize-observer | 3.4.0 | Apache-2.0 | https://github.com/juggle/resize-observer |
| @maskito/core | 1.9.0 | Apache-2.0 | https://github.com/taiga-family/maskito |
| @maskito/core | 4.0.1 | Apache-2.0 | https://github.com/taiga-family/maskito |
| @maskito/kit | 4.0.1 | Apache-2.0 | https://github.com/taiga-family/maskito |
| @maskito/react | 1.9.0 | Apache-2.0 | https://github.com/taiga-family/maskito |
| @popperjs/core | 2.11.8 | MIT | https://github.com/popperjs/popper-core |
| @reach/observe-rect | 1.2.0 | MIT | https://github.com/reach/observe-rect |
| @reduxjs/toolkit | 2.13.0 | MIT | https://github.com/reduxjs/redux-toolkit |
| @standard-schema/spec | 1.1.0 | MIT | https://github.com/standard-schema/standard-schema |
| @standard-schema/utils | 0.3.0 | MIT | https://github.com/standard-schema/standard-schema |
| @tanstack/query-core | 5.104.5 | MIT | https://github.com/TanStack/query |
| @tanstack/react-query | 5.104.5 | MIT | https://github.com/TanStack/query |
| @types/d3-array | 3.2.2 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-color | 3.1.3 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-drag | 3.0.7 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-ease | 3.0.2 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-interpolate | 3.0.4 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-path | 3.1.1 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-scale | 4.0.9 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-selection | 3.0.12 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-shape | 3.2.0 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-time | 3.0.4 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-timer | 3.0.2 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-transition | 3.0.9 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/d3-zoom | 3.0.9 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/debug | 4.1.13 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/estree-jsx | 1.0.5 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/estree | 1.0.9 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/hast | 3.0.5 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/mdast | 4.0.4 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/ms | 2.1.0 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react-dom | 19.3.0 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react-transition-group | 4.4.12 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react | 19.3.0 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/unist | 2.0.11 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/unist | 3.0.3 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/use-sync-external-store | 0.0.6 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @ungap/structured-clone | 1.4.0 | ISC | https://github.com/ungap/structured-clone |
| @xyflow/react | 12.12.0 | MIT | https://github.com/xyflow/xyflow |
| @xyflow/system | 0.0.83 | MIT | https://github.com/xyflow/xyflow |
| bail | 2.0.2 | MIT | https://github.com/wooorm/bail |
| can-use-dom | 0.1.0 | MIT | https://github.com/akiran/can-use-dom |
| ccount | 2.0.1 | MIT | https://github.com/wooorm/ccount |
| character-entities-html4 | 2.1.0 | MIT | https://github.com/wooorm/character-entities-html4 |
| character-entities-legacy | 1.1.4 | MIT | https://github.com/wooorm/character-entities-legacy |
| character-entities-legacy | 3.0.0 | MIT | https://github.com/wooorm/character-entities-legacy |
| character-entities | 1.2.4 | MIT | https://github.com/wooorm/character-entities |
| character-entities | 2.0.2 | MIT | https://github.com/wooorm/character-entities |
| character-reference-invalid | 1.1.4 | MIT | https://github.com/wooorm/character-reference-invalid |
| character-reference-invalid | 2.0.1 | MIT | https://github.com/wooorm/character-reference-invalid |
| classcat | 5.0.5 | MIT | https://github.com/jorgebucaran/classcat |
| classnames | 2.5.1 | MIT | https://github.com/JedWatson/classnames |
| clsx | 2.1.1 | MIT | https://github.com/lukeed/clsx |
| comma-separated-tokens | 2.0.3 | MIT | https://github.com/wooorm/comma-separated-tokens |
| compute-scroll-into-view | 3.1.1 | MIT | https://github.com/scroll-into-view/compute-scroll-into-view |
| cookie | 1.1.1 | MIT | https://github.com/jshttp/cookie |
| core-js | 3.51.0 | MIT | https://github.com/zloirock/core-js |
| csstype | 3.2.3 | MIT | https://github.com/frenic/csstype |
| d3-array | 3.2.4 | ISC | https://github.com/d3/d3-array |
| d3-color | 3.1.0 | ISC | https://github.com/d3/d3-color |
| d3-dispatch | 3.0.1 | ISC | https://github.com/d3/d3-dispatch |
| d3-drag | 3.0.0 | ISC | https://github.com/d3/d3-drag |
| d3-ease | 3.0.1 | BSD-3-Clause | https://github.com/d3/d3-ease |
| d3-format | 3.1.2 | ISC | https://github.com/d3/d3-format |
| d3-interpolate | 3.0.1 | ISC | https://github.com/d3/d3-interpolate |
| d3-path | 3.1.0 | ISC | https://github.com/d3/d3-path |
| d3-scale | 4.0.2 | ISC | https://github.com/d3/d3-scale |
| d3-selection | 3.0.0 | ISC | https://github.com/d3/d3-selection |
| d3-shape | 3.2.0 | ISC | https://github.com/d3/d3-shape |
| d3-time-format | 4.1.0 | ISC | https://github.com/d3/d3-time-format |
| d3-time | 3.1.0 | ISC | https://github.com/d3/d3-time |
| d3-timer | 3.0.1 | ISC | https://github.com/d3/d3-timer |
| d3-transition | 3.0.1 | ISC | https://github.com/d3/d3-transition |
| d3-zoom | 3.0.0 | ISC | https://github.com/d3/d3-zoom |
| date-fns | 4.4.0 | MIT | https://github.com/date-fns/date-fns |
| debug | 4.4.3 | MIT | https://github.com/debug-js/debug |
| decimal.js-light | 2.5.1 | MIT | https://github.com/MikeMcl/decimal.js-light |
| decode-named-character-reference | 1.3.0 | MIT | https://github.com/wooorm/decode-named-character-reference |
| dequal | 2.0.3 | MIT | https://github.com/lukeed/dequal |
| detect-browser | 5.3.0 | MIT | https://github.com/DamonOehlman/detect-browser |
| detect-node-es | 1.1.0 | MIT | https://github.com/thekashey/detect-node |
| devlop | 1.1.0 | MIT | https://github.com/wooorm/devlop |
| dom-helpers | 5.2.1 | MIT | https://github.com/react-bootstrap/dom-helpers |
| downshift | 8.4.0 | MIT | https://github.com/downshift-js/downshift |
| element-closest | 3.0.2 | CC0-1.0 | https://github.com/jonathantneal/closest |
| es-toolkit | 1.52.0 | MIT | https://github.com/toss/es-toolkit |
| estree-util-is-identifier-name | 3.0.0 | MIT | https://github.com/syntax-tree/estree-util-is-identifier-name |
| eventemitter3 | 4.0.7 | MIT | https://github.com/primus/eventemitter3 |
| eventemitter3 | 5.0.4 | MIT | https://github.com/primus/eventemitter3 |
| extend | 3.0.2 | MIT | https://github.com/justmoon/node-extend |
| fast-equals | 5.4.5 | MIT | https://github.com/planttheidea/fast-equals |
| focus-lock | 1.3.6 | MIT | https://github.com/theKashey/focus-lock |
| get-nonce | 1.0.1 | MIT | https://github.com/theKashey/get-nonce |
| hast-util-to-jsx-runtime | 2.3.6 | MIT | https://github.com/syntax-tree/hast-util-to-jsx-runtime |
| hast-util-whitespace | 3.0.0 | MIT | https://github.com/syntax-tree/hast-util-whitespace |
| hls.js | 1.7.3 | Apache-2.0 | https://github.com/video-dev/hls.js |
| html-url-attributes | 3.0.1 | MIT | https://github.com/rehypejs/rehype-minify/tree/main/packages/html-url-attributes |
| immer | 11.2.9 | MIT | https://github.com/immerjs/immer |
| inline-style-parser | 0.2.7 | MIT | https://github.com/remarkablemark/inline-style-parser |
| internmap | 2.0.3 | ISC | https://github.com/mbostock/internmap |
| intersection-observer | 0.12.2 | Apache-2.0 | https://github.com/GoogleChromeLabs/intersection-observer |
| is-alphabetical | 1.0.4 | MIT | https://github.com/wooorm/is-alphabetical |
| is-alphabetical | 2.0.1 | MIT | https://github.com/wooorm/is-alphabetical |
| is-alphanumerical | 1.0.4 | MIT | https://github.com/wooorm/is-alphanumerical |
| is-alphanumerical | 2.0.1 | MIT | https://github.com/wooorm/is-alphanumerical |
| is-decimal | 1.0.4 | MIT | https://github.com/wooorm/is-decimal |
| is-decimal | 2.0.1 | MIT | https://github.com/wooorm/is-decimal |
| is-hexadecimal | 1.0.4 | MIT | https://github.com/wooorm/is-hexadecimal |
| is-hexadecimal | 2.0.1 | MIT | https://github.com/wooorm/is-hexadecimal |
| is-plain-obj | 4.1.0 | MIT | https://github.com/sindresorhus/is-plain-obj |
| js-tokens | 4.0.0 | MIT | https://github.com/lydell/js-tokens |
| libphonenumber-js | 1.13.15 | MIT | git+https://gitlab.com/catamphetamine/libphonenumber-js |
| lodash-es | 4.18.1 | MIT | https://github.com/lodash/lodash |
| lodash.debounce | 4.0.8 | MIT | https://github.com/lodash/lodash |
| lodash.memoize | 4.1.2 | MIT | https://github.com/lodash/lodash |
| lodash.throttle | 4.1.1 | MIT | https://github.com/lodash/lodash |
| lodash | 4.18.1 | MIT | https://github.com/lodash/lodash |
| longest-streak | 2.0.4 | MIT | https://github.com/wooorm/longest-streak |
| longest-streak | 3.1.0 | MIT | https://github.com/wooorm/longest-streak |
| loose-envify | 1.4.0 | MIT | https://github.com/zertosh/loose-envify |
| lottie-web | 5.13.0 | MIT | https://github.com/airbnb/lottie-web |
| mdast-util-from-markdown | 2.1.0 | MIT | https://github.com/syntax-tree/mdast-util-from-markdown |
| mdast-util-gfm-strikethrough | 0.2.3 | MIT | https://github.com/syntax-tree/mdast-util-gfm-strikethrough |
| mdast-util-mdx-expression | 2.0.1 | MIT | https://github.com/syntax-tree/mdast-util-mdx-expression |
| mdast-util-mdx-jsx | 3.2.0 | MIT | https://github.com/syntax-tree/mdast-util-mdx-jsx |
| mdast-util-mdxjs-esm | 2.0.1 | MIT | https://github.com/syntax-tree/mdast-util-mdxjs-esm |
| mdast-util-phrasing | 4.1.0 | MIT | https://github.com/syntax-tree/mdast-util-phrasing |
| mdast-util-to-hast | 13.2.1 | MIT | https://github.com/syntax-tree/mdast-util-to-hast |
| mdast-util-to-markdown | 0.6.5 | MIT | https://github.com/syntax-tree/mdast-util-to-markdown |
| mdast-util-to-markdown | 2.2.0 | MIT | https://github.com/syntax-tree/mdast-util-to-markdown |
| mdast-util-to-string | 2.0.0 | MIT | https://github.com/syntax-tree/mdast-util-to-string |
| mdast-util-to-string | 4.0.0 | MIT | https://github.com/syntax-tree/mdast-util-to-string |
| micromark-core-commonmark | 2.0.4 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-core-commonmark |
| micromark-extension-gfm-strikethrough | 0.6.5 | MIT | https://github.com/micromark/micromark-extension-gfm-strikethrough |
| micromark-factory-destination | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-factory-destination |
| micromark-factory-label | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-factory-label |
| micromark-factory-space | 2.1.0 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-factory-space |
| micromark-factory-title | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-factory-title |
| micromark-factory-whitespace | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-factory-whitespace |
| micromark-util-character | 2.1.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-character |
| micromark-util-chunked | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-chunked |
| micromark-util-classify-character | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-classify-character |
| micromark-util-combine-extensions | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-combine-extensions |
| micromark-util-decode-numeric-character-reference | 2.0.2 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-decode-numeric-character-reference |
| micromark-util-decode-string | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-decode-string |
| micromark-util-edit-map | 1.0.0 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-edit-map |
| micromark-util-encode | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-encode |
| micromark-util-html-tag-name | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-html-tag-name |
| micromark-util-normalize-identifier | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-normalize-identifier |
| micromark-util-resolve-all | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-resolve-all |
| micromark-util-sanitize-uri | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-sanitize-uri |
| micromark-util-subtokenize | 2.1.0 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-subtokenize |
| micromark-util-symbol | 2.0.1 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-symbol |
| micromark-util-types | 2.0.3 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark-util-types |
| micromark | 2.11.4 | MIT | https://github.com/micromark/micromark |
| micromark | 4.0.3 | MIT | https://github.com/micromark/micromark/tree/main/packages/micromark |
| ms | 2.1.3 | MIT | https://github.com/vercel/ms |
| nouislider | 15.8.1 | MIT | https://github.com/leongersen/noUiSlider |
| object-assign | 4.1.1 | MIT | https://github.com/sindresorhus/object-assign |
| openapi-fetch | 0.15.0 | MIT | https://github.com/openapi-ts/openapi-typescript |
| openapi-typescript-helpers | 0.0.15 | MIT | https://github.com/openapi-ts/openapi-typescript |
| parse-entities | 2.0.0 | MIT | https://github.com/wooorm/parse-entities |
| parse-entities | 4.0.2 | MIT | https://github.com/wooorm/parse-entities |
| popper-max-size-modifier | 0.2.0 | MIT |  |
| prop-types | 15.8.1 | MIT | https://github.com/facebook/prop-types |
| property-information | 7.2.0 | MIT | https://github.com/wooorm/property-information |
| react-canvas-pattern-lock | 2.0.7 | не указана (см. раздел 1) | https://github.com/Lacronts/react-canvas-pattern-lock |
| react-clientside-effect | 1.2.8 | MIT | https://github.com/thekashey/react-clientside-effect |
| react-div-100vh | 0.7.0 | MIT | https://github.com/mvasin/react-div-100vh |
| react-dom | 19.3.1 | MIT | https://github.com/react/react |
| react-fast-compare | 3.2.2 | MIT | https://github.com/FormidableLabs/react-fast-compare |
| react-focus-lock | 2.13.7 | MIT | https://github.com/theKashey/react-focus-lock |
| react-is | 16.13.1 | MIT | https://github.com/facebook/react |
| react-is | 17.0.2 | MIT | https://github.com/facebook/react |
| react-is | 18.3.1 | MIT | https://github.com/facebook/react |
| react-markdown | 9.1.0 | MIT | https://github.com/remarkjs/react-markdown |
| react-merge-refs | 1.1.0 | MIT | https://github.com/gregberge/react-merge-refs |
| react-popper | 2.3.0 | MIT | https://github.com/popperjs/react-popper |
| react-redux | 9.3.0 | MIT | https://github.com/reduxjs/react-redux |
| react-remove-scroll-bar | 2.3.8 | MIT | https://github.com/theKashey/react-remove-scroll-bar |
| react-remove-scroll | 2.7.2 | MIT | https://github.com/theKashey/react-remove-scroll |
| react-router | 7.18.4 | MIT | https://github.com/remix-run/react-router |
| react-smooth | 4.0.4 | MIT | https://github.com/recharts/react-smooth |
| react-style-singleton | 2.2.3 | MIT | https://github.com/theKashey/react-style-singleton |
| react-swipeable | 7.0.2 | MIT | https://github.com/FormidableLabs/react-swipeable |
| react-textarea-autosize | 8.5.9 | MIT | https://github.com/Andarist/react-textarea-autosize |
| react-transition-group | 4.4.5 | BSD-3-Clause | https://github.com/reactjs/react-transition-group |
| react-use-event-hook | 0.9.6 | MIT | https://github.com/scottrippey/react-use-event-hook |
| react-virtual | 2.10.4 | MIT | https://github.com/tannerlinsley/react-virtual |
| react-virtuoso | 4.18.19 | MIT | https://github.com/petyosi/react-virtuoso |
| react | 19.3.1 | MIT | https://github.com/react/react |
| recharts-scale | 0.4.5 | MIT | https://github.com/recharts/recharts-scale |
| recharts | 2.15.4 | MIT | https://github.com/recharts/recharts |
| recharts | 3.10.1 | MIT | https://github.com/recharts/recharts |
| redux-thunk | 3.1.0 | MIT | https://github.com/reduxjs/redux-thunk |
| redux | 5.0.1 | MIT | https://github.com/reduxjs/redux |
| remark-parse | 11.0.0 | MIT | https://github.com/remarkjs/remark/tree/main/packages/remark-parse |
| remark-rehype | 11.1.2 | MIT | https://github.com/remarkjs/remark-rehype |
| repeat-string | 1.6.1 | MIT | https://github.com/jonschlinkert/repeat-string |
| reselect | 5.2.0 | MIT | https://github.com/reduxjs/reselect |
| scheduler | 0.28.0 | MIT | https://github.com/react/react |
| set-cookie-parser | 2.7.3 | MIT | https://github.com/nfriedly/set-cookie-parser |
| simplebar-core | 1.3.2 | MIT | https://github.com/grsmto/simplebar |
| simplebar-react | 3.3.2 | MIT | https://github.com/grsmto/simplebar |
| simplebar | 5.3.9 | MIT | https://github.com/grsmto/simplebar |
| space-separated-tokens | 2.0.2 | MIT | https://github.com/wooorm/space-separated-tokens |
| stringify-entities | 4.0.4 | MIT | https://github.com/wooorm/stringify-entities |
| style-to-js | 1.1.21 | MIT | https://github.com/remarkablemark/style-to-js |
| style-to-object | 1.0.14 | MIT | https://github.com/remarkablemark/style-to-object |
| swiper | 12.2.0 | MIT | https://github.com/nolimits4web/Swiper |
| text-mask-core | 5.1.2 | Unlicense | https://github.com/text-mask/text-mask |
| tiny-invariant | 1.3.3 | MIT | https://github.com/alexreardon/tiny-invariant |
| trim-lines | 3.0.1 | MIT | https://github.com/wooorm/trim-lines |
| trough | 2.2.0 | MIT | https://github.com/wooorm/trough |
| tslib | 2.8.1 | 0BSD | https://github.com/Microsoft/tslib |
| unified | 11.0.5 | MIT | https://github.com/unifiedjs/unified |
| unist-util-is | 6.0.1 | MIT | https://github.com/syntax-tree/unist-util-is |
| unist-util-position | 5.0.0 | MIT | https://github.com/syntax-tree/unist-util-position |
| unist-util-stringify-position | 4.0.0 | MIT | https://github.com/syntax-tree/unist-util-stringify-position |
| unist-util-visit-parents | 6.0.2 | MIT | https://github.com/syntax-tree/unist-util-visit-parents |
| unist-util-visit | 5.1.0 | MIT | https://github.com/syntax-tree/unist-util-visit |
| use-callback-ref | 1.3.3 | MIT | https://github.com/theKashey/use-callback-ref |
| use-composed-ref | 1.4.0 | MIT | https://github.com/Andarist/use-composed-ref |
| use-isomorphic-layout-effect | 1.2.1 | MIT | https://github.com/Andarist/use-isomorphic-layout-effect |
| use-latest | 1.3.0 | MIT | https://github.com/Andarist/use-latest |
| use-sidecar | 1.1.3 | MIT | https://github.com/theKashey/use-sidecar |
| use-sync-external-store | 1.7.0 | MIT | https://github.com/react/react |
| uuid | 14.0.3 | MIT | https://github.com/uuidjs/uuid |
| vfile-message | 4.0.3 | MIT | https://github.com/vfile/vfile-message |
| vfile | 6.0.3 | MIT | https://github.com/vfile/vfile |
| victory-vendor | 36.9.2 | MIT AND ISC | https://github.com/FormidableLabs/victory |
| victory-vendor | 37.3.6 | MIT AND ISC | https://github.com/FormidableLabs/victory |
| warning | 4.0.3 | MIT | https://github.com/BerkeleyTrue/warning |
| zustand | 4.5.7 | MIT | https://github.com/pmndrs/zustand |
| zustand | 5.0.16 | MIT | https://github.com/pmndrs/zustand |
| zwitch | 1.0.5 | MIT | https://github.com/wooorm/zwitch |
| zwitch | 2.0.4 | MIT | https://github.com/wooorm/zwitch |
