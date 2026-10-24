# 13. Развёртывание, CI, демо и сдача

## 1. Окружения

| Окружение | Как запускается | LLM | Данные |
|---|---|---|---|
| Локальная разработка | `make dev-api`, `make dev-worker`, `make dev-web` | `fake` для UI, `live` для ручных проверок | synthetic |
| Локальный Docker | `make up` | `replay` или `live` | synthetic или real |
| Прод (демо для жюри) | `docker compose up -d` на VPS | `live` (фича B), демо-содержимое из кеша | synthetic или real (решение команды) |

`settings.py` сам находит корень репозитория: поднимается вверх до каталога с `config/`. По умолчанию `DATA_DIR = <root>/data`, `CONFIG_DIR = <root>/config`. В Docker обе переменные задаются явно.

## 2. Переменные окружения (`.env.example`)

```dotenv
# ── LLM ──
LLM_BASE_URL=https://<адрес-шлюза>/v1
LLM_BASE_URL_FALLBACK=
LLM_API_KEY=
LLM_MODE=live                      # live | replay | fake
LLM_DAILY_BUDGET_RUB=450
LLM_INTERACTIVE_RESERVE_RUB=150
LLM_MAX_RUN_COST_RUB=5
BUDGET_TZ=Europe/Moscow
VERIFY_LLM_SKIP_IF_CLEAN=false
TAG_BODY_CHARS=6000

# ── Приложение ──
APP_ENV=dev                        # dev | prod
APP_TZ=Europe/Moscow
LOG_LEVEL=INFO
# Пусто → <корень>/data и <корень>/config; в Docker задаются в docker-compose.yml (/app/data, /app/config).
# Комментарий не пишется в строке с пустым значением: docker compose прочитает его как значение.
DATA_DIR=
CONFIG_DIR=
DATA_PROFILE=synthetic             # synthetic | real
TARGET_REVENUE_RUB=15000000000
SESSION_SECRET=change-me-32-bytes-minimum
COOKIE_SECURE=false
DEMO_MODE=true
JURY_CODE=
ADMIN_TOKEN=

# ── Агент ──
AGENT_MAX_CONCURRENT_RUNS=4
AGENT_RUN_TIMEOUT_S=60

# ── Worker ──
RUN_WORKER_IN_API=false            # true — планировщик внутри процесса api (хостинги с одним сервисом)
INGEST_ENABLED=true
INGEST_GEO=any                     # any | ru (включает источники с geo: ru)
INGEST_RSS_INTERVAL_MIN=15
RSS_MAX_AGE_DAYS=7
PREFILTER_MIN_SCORE=3
SIMHASH_MAX_DISTANCE=3
CLUSTER_SIM_THRESHOLD=0.30
PIPELINE_TICK_MAX_COST_RUB=5
PRECOMPUTE_ENABLED=true
PRECOMPUTE_COMPANIES=demo          # demo | all | список company_id через запятую
SEED_SHIFT_TO_NOW=true
INIT_MAX_COST_RUB=10               # лимит на разметку seed при init, если кеша не хватило
WEB_PORT=8080
```

`Settings` (pydantic-settings) описывает все переменные с типами и умолчаниями. При `APP_ENV=prod` и `DEMO_MODE=false` секреты проверяются (`11-security.md` §2).

## 3. Docker

### 3.1 `backend/Dockerfile` (контекст сборки — корень репозитория)

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY config/ /app/config/
COPY data/reference/ /app/data/reference/
COPY data/synthetic/ /app/data/synthetic/
COPY data/seed/ /app/data/seed/
RUN useradd -m -u 10001 app && mkdir -p /app/data/runtime /app/data/raw && chown -R app /app/data/runtime
COPY --chmod=755 backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/app/backend/.venv/bin:$PATH" DATA_DIR=/app/data CONFIG_DIR=/app/config
EXPOSE 8000
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "alfa_insight.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

Том `./data/runtime` на хосте создаётся docker от root, поэтому контейнер стартует от root: `docker-entrypoint.sh` отдаёт том пользователю `app` (`chown`) и запускает процесс от него через `setpriv`. `.dockerignore` не пускает в образ `.env`, `data/raw/` и `data/runtime/`.

### 3.2 `frontend/Dockerfile`

```dockerfile
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
```

### 3.3 `frontend/nginx.conf`

```nginx
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  client_max_body_size 64k;

  add_header X-Content-Type-Options nosniff always;
  add_header Referrer-Policy strict-origin-when-cross-origin always;
  add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
  add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" always;

  location /api/ {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Connection "";
    proxy_buffering off;          # SSE
    proxy_cache off;
    proxy_read_timeout 600s;
  }

  location /assets/ {
    expires 1y;                   # не add_header: иначе потеряются заголовки уровня server
  }

  location / {
    try_files $uri /index.html;
  }
}
```

### 3.4 `docker-compose.yml`

```yaml
x-backend: &backend
  build: {context: ., dockerfile: backend/Dockerfile}
  env_file: .env
  environment: {DATA_DIR: /app/data, CONFIG_DIR: /app/config}
  volumes:
    - ./data/runtime:/app/data/runtime
    - ./data/raw:/app/data/raw:ro

services:
  init:
    <<: *backend
    command: ["alfa", "init"]
    restart: "no"

  api:
    <<: *backend
    depends_on: {init: {condition: service_completed_successfully}}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/ready', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  worker:
    <<: *backend
    command: ["alfa", "worker"]
    depends_on: {init: {condition: service_completed_successfully}}
    restart: unless-stopped

  web:
    build: {context: ., dockerfile: frontend/Dockerfile}
    ports: ["${WEB_PORT:-8080}:80"]
    depends_on: {api: {condition: service_healthy}}
    restart: unless-stopped
```

`GET /api/ready` отвечает **503**, пока не готов, и 200 после готовности, поэтому healthcheck работает без разбора тела.

### 3.5 `alfa init` (идемпотентный)

1. `db migrate`.
2. `data build` (пропускается, если не изменились исходники и справочники). Если `DATA_PROFILE=real`, а `data/raw` пуст, выводится ошибка с подсказкой «поставьте `DATA_PROFILE=synthetic`».
3. `llm cache import data/seed/llm_cache_demo.jsonl` — до разметки, чтобы seed размечался из кеша бесплатно.
4. `ingest seed --shift-to-now` (если `SEED_SHIFT_TO_NOW`). Новые строки получают сдвиг. У загруженных строк даты пересчитываются от оригиналов из JSONL, вместе с `first_seen_at` и `last_seen_at` их событий.
5. `pipeline run --until clustered --max-cost $INIT_MAX_COST_RUB`.
6. `research ingest`, если в `data/raw/research/` есть PDF.
7. `macro refresh`, при ошибке — загрузка снимка `data/seed/macro.json`.
8. `rank all`.

**Что показывает `replay` из чистого клона** (проверено 24.10.2026: `cp .env.example .env`, `LLM_MODE=replay`, `docker compose up -d --build`): разметка 630 seed-новостей берётся из `llm_cache_demo.jsonl` бесплатно, ставка и курсы — из снимка, лента, цепочки влияния, профиль и брифинги работают. Готовых разборов нет: аналитика Альфа-Банка собирается только из PDF кейса в `data/raw/research/`, а их и выдержки из них публиковать нельзя, поэтому кеш черновиков и инсайтов не выгружается. Попытка разбора в `replay` завершается кодом `llm_unavailable`, баннер «новые разборы недоступны» предупреждает об этом заранее. Полное демо — `LLM_MODE=live` с ключом шлюза.

## 4. Хостинг

| Вариант | Плюсы | Минусы | Вердикт |
|---|---|---|---|
| **VPS с Docker** (российский: Timeweb Cloud, Selectel, Yandex Cloud; или любой зарубежный) | Постоянный диск, SSE без ограничений, полный контроль. Российский IP даёт доступ к РБК и, возможно, к шлюзу | 30–60 минут на настройку | **Рекомендуется** |
| Railway с volume | Деплой из GitHub за минуты | Платно после триала, зарубежный IP, один volume на сервис → `RUN_WORKER_IN_API=true` (один процесс) | Запасной |
| Render free | Бесплатно | Нет постоянного диска, засыпает, холодный старт | Не подходит (ADR-18) |

**Минимальный VPS:** 2 vCPU, 4 ГБ RAM, 20 ГБ диска.

**Шаги на VPS:**

```bash
# 1. Docker и плагин compose (по официальной инструкции дистрибутива)
git clone https://github.com/nedreyner/alfa-hackathon-2026.git && cd alfa-hackathon-2026
cp .env.example .env && nano .env              # ключ шлюза, SESSION_SECRET, APP_ENV=prod, COOKIE_SECURE=true
# 2. (опционально) реальные данные: scp в data/raw/, DATA_PROFILE=real
docker compose up -d --build
docker compose logs -f init                    # дождаться завершения
# 3. HTTPS: Caddy на хосте
caddy reverse-proxy --from insight.<домен> --to localhost:8080
# 4. Смоук-проверка
curl -fsS https://insight.<домен>/api/ready
```

Если шлюз доступен только из РФ, а хост зарубежный, задаётся `LLM_BASE_URL_FALLBACK` (запасной адрес шлюза для российских хостингов). Иначе хост выбирается в РФ, и выставляется `INGEST_GEO=ru`.

## 5. CI (`.github/workflows/ci.yml`)

```yaml
name: ci
on: [push, pull_request]
jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: backend}}
    env: {LLM_MODE: fake}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with: {python-version: "3.12"}
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy alfa_insight
      - run: uv run pytest -q
      - run: uv run alfa api openapi --out /tmp/openapi.json && diff -q /tmp/openapi.json ../frontend/openapi.json
  frontend:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: frontend}}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: {node-version: 22, cache: npm, cache-dependency-path: frontend/package-lock.json}
      - run: npm ci
      - run: npm run gen:api && git diff --exit-code src/api/schema.d.ts
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      - run: npm run build
  docker:
    if: github.ref == 'refs/heads/main'
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose build
```

Отдельная задача `secrets` — `gitleaks` по всей истории (`gitleaks/gitleaks-action@v2`).

## 6. Демо

### 6.1 Подготовка («заморозка», ADR-19)

1. **За 1–2 дня:** `LLM_MODE=live`. Свежий seed (`alfa seed collect` несколько дней подряд), `make seed`, `alfa precompute --companies demo --top-k 5`. Вручную пройти чеклист: у каждой демо-компании ≥ 3 сильных инсайта, цепочки осмысленны, позиция банка найдена, нет `needs_review`.
2. `alfa demo freeze`: экспорт записей `llm_cache` с разметкой seed-новостей (текущая версия промпта, `request` не выгружается — текст новостей уже в `news.jsonl`) в `data/seed/llm_cache_demo.jsonl`, плюс снимок ставки и курсов в `macro.json`. Записи прогонов демо-компаний не выгружаются: в них выдержки из PDF аналитики, которые нельзя публиковать (см. §3.5). Коммит и деплой.
3. **В день показа:** `LLM_MODE=live`, потому что фиче B нужна живая модель. Демо-контент отдаётся из готовых инсайтов и кеша мгновенно. Заранее открыть все демо-карточки, все должны быть `ready`.
4. **Если шлюз упал:** `LLM_MODE=replay` и перезапуск `api` и `worker`. Всё, кроме новых новостей, работает. Для фичи B — заготовленный пример из кеша.
5. **Резерв:** ноутбук с `docker compose up` в `replay` и видео сценария (3 мин).

### 6.2 Сценарий (7 минут)

| Время | Экран | Что показываем |
|---|---|---|
| 0:00–0:40 | Вход → главная «Альфа-Бизнес» (SYN-DEMO-02 «Волга-Строй», роль «Финансовый директор») | Новостей тысячи, важны три. Виджет «Сегодня важно для вас» прямо в интернет-банке |
| 0:40–2:00 | Карточка «Арматура дорожает: себестоимость ваших объектов может вырасти» | Шесть ответов. **Цепная реакция:** событие → металлургия → 34% ваших закупок → себестоимость. Метки «Факт», «Альфа-Банк», «Вывод ИИ». Клик по факту открывает первоисточник. Продукт «Кредитная линия» с подтверждением |
| 2:00–2:40 | «Как мы пришли к выводу» | План → инструменты → проверка «9 из 10 подтверждены» → доработка. Модели, время, стоимость в рублях |
| 2:40–3:20 | Чат: «А если ставка снизится до 12%?» | Ответ с данными ЦБ и позицией аналитиков банка, метки и источники |
| 3:20–3:50 | Смена роли на «Казначей» | Брифинг перестраивается: процентные и валютные риски наверху |
| 3:50–5:20 | «Проверить новость»: **жюри даёт свежую ссылку** | Шаги вживую, разбор примерно за 20 секунд. Если связь с компанией слабая, сервис честно это говорит |
| 5:20–6:10 | «Что мы о вас знаем» → «добавить экспорт в Казахстан» | Профиль обновлён, лента пересчиталась |
| 6:10–7:00 | «Качество» | nDCG@5: цепная реакция против «только отрасль». Обоснованность, стоимость инсайта, бюджет |

**План Б по шагам:**
- Нет нужной свежей новости → заготовленная ссылка из `ANALYZE_EXAMPLES`.
- Фича B упала → текстовая вкладка с заранее скопированным текстом.
- Медленная сеть → видео.

## 7. Чеклист сдачи

- [ ] **README.md:** что это и для кого; ссылка на демо; скриншоты; быстрый старт (`cp .env.example .env && docker compose up`, работает на синтетике и `replay` без ключа); архитектура (схема из `02-architecture.md`); данные (синтетика, как подключить реальные); модели и бюджет (расчёт из `04-llm.md` §7.4 на реальных ценах); безопасность (сводка `11-security.md`); метрики (таблица из `eval/reports/latest.md`); ограничения и допущения; команда.
- [ ] **THIRD_PARTY_NOTICES.md:** Python-зависимости (`uv run pip-licenses --format=markdown --with-urls`), JS-зависимости (`npx license-checker --production --summary` и список), дизайн-система `@alfalab/core-components` (MIT), LLM через шлюз хакатона, тексты новостей (принадлежат правообладателям, фрагменты до 3000 символов со ссылкой), данные кейса (не публикуются).
- [ ] **LICENSE** (MIT, решение команды).
- [ ] **Синтетические данные** (`data/synthetic/`), генератор (`alfa data synth`) и описание в README.
- [ ] **OpenAPI:** `/api/docs`, `frontend/openapi.json`.
- [ ] **Развёрнутая версия**, `GET /api/ready` = 200, проверка фичи B на свежей новости.
- [ ] **Сценарий демо** (§6.2) и видео-резерв.
- [ ] **Отчёт метрик:** `eval/reports/latest.json` и `latest.md`.
- [ ] `gitleaks` чистый, в истории нет `data/raw` и `.env`.
- [ ] **Тег версии** на коммите до дедлайна: `git tag -a v1.0.0 -m "Сдача на хакатон" && git push origin v1.0.0`.

## 8. Makefile

```make
.PHONY: setup check test data seed dev-api dev-worker dev-web openapi up down eval

setup:
	cd backend && uv sync
	cd frontend && npm ci

check:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy alfa_insight
	cd frontend && npm run lint && npm run typecheck

test:
	cd backend && LLM_MODE=fake uv run pytest -q
	cd frontend && npm test

data:
	cd backend && uv run alfa db migrate && uv run alfa data build

seed:
	cd backend && uv run alfa llm cache import ../data/seed/llm_cache_demo.jsonl \
	  && uv run alfa ingest seed --shift-to-now \
	  && uv run alfa pipeline run --until clustered --max-cost 10 \
	  && uv run alfa rank all

dev-api:
	cd backend && uv run uvicorn alfa_insight.api.app:create_app --factory --reload --port 8000

dev-worker:
	cd backend && uv run alfa worker

dev-web:
	cd frontend && npm run dev

openapi:
	cd backend && uv run alfa api openapi --out ../frontend/openapi.json
	cd frontend && npm run gen:api

up:
	docker compose up -d --build

down:
	docker compose down

eval:
	cd backend && uv run alfa eval ranking --baselines && uv run alfa eval report
```
