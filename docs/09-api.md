# 09. REST API и SSE

## 1. Общие правила

- Все пути начинаются с `/api`. Запросы и ответы — JSON в UTF-8. Каждый роут объявляет `response_model`. `operation_id` = имя функции роута: так в TS-клиенте получаются понятные имена.
- Время — ISO 8601 в UTC с `Z`. Деньги — `float` в рублях. Доли — `float` от 0 до 1. `event_id` и `news_id` — целые, остальные id — строки (`run_…`, `ins_…`).
- Пагинация курсорная: `?limit=20&cursor=<непрозрачная строка>`, в ответе `next_cursor` (`null` — конец).
- Тонкие роуты: валидация → вызов сервиса → DTO. Код — `api/routes/<группа>.py`, DTO — `api/schemas.py` (переиспользуют модели из `agent/schemas.py`, `data/models.py` и др., без копий).
- Сессия — подписанная cookie `ai_session` (§2). Без сессии доступны только `GET /api/health`, `/api/ready`, `/api/meta`, `/api/reference`, `/api/demo/companies` и `POST /api/session`. Остальные отвечают `401 unauthorized`.
- Админские эндпоинты требуют заголовок `X-Admin-Token: <ADMIN_TOKEN>`. Если `ADMIN_TOKEN` пуст, они отключены (404).

## 2. Сессия и доступ (`api/session.py`)

```python
class SessionData(BaseModel):          # содержимое cookie (подписано itsdangerous.URLSafeTimedSerializer)
    sid: str                           # случайный id сессии (secrets.token_urlsafe(16))
    company_id: str
    role: Role
    jury: bool
    iat: int
```

- Cookie: `ai_session`, `HttpOnly`, `SameSite=Lax`, `Secure` при `COOKIE_SECURE=true`, `Path=/`, `Max-Age` 7 суток. Подпись — `SESSION_SECRET`, соль `"ai-session"`.
- **Вход:** `POST /api/session {company_id, role, jury_code?}`. Компания должна быть целевой. При `DEMO_MODE=true` разрешена любая целевая компания. При `DEMO_MODE=false` — только демо-компании, остальные при `jury_code == JURY_CODE` (тогда `jury=true`).
- **Скоуп:** каждый эндпоинт с данными компании берёт `company_id` только из сессии. Объекты другой компании (инсайт, прогон, источник `client_data`, приватное событие) дают `404 not_found`, а не `403`: так не раскрывается факт их существования.
- **Смена компании** — новый `POST /api/session`. Смена роли — `PATCH /api/session`.

## 3. Эндпоинты

| Метод | Путь | Назначение | Ответ |
|---|---|---|---|
| GET | `/api/health` | Процесс жив | `{status, version}` |
| GET | `/api/ready` | Готовность: БД, DuckDB, профили, миграции | `ReadyResponse` (200 — готов, 503 — нет) |
| GET | `/api/meta` | Режимы для баннеров UI | `MetaResponse` |
| GET | `/api/demo/companies?q=&limit=` | Компании для входа | `list[CompanySummary]` |
| GET | `/api/reference` | Справочники для UI: отрасли, факторы, страны, типы событий, роли, продукты | `ReferenceResponse` |
| POST | `/api/session` | Вход | `SessionInfo` + cookie |
| GET | `/api/session` | Текущая сессия | `SessionInfo` |
| PATCH | `/api/session` | Сменить роль | `SessionInfo` |
| DELETE | `/api/session` | Выход | 204 |
| GET | `/api/me/profile` | «Что мы о вас знаем» | `ProfileResponse` |
| GET | `/api/me/counterparties?direction=&industry_id=&limit=` | Контрагенты и структура | `CounterpartiesResponse` |
| PUT | `/api/me/profile/overrides` | Правки профиля | `ProfileResponse` |
| GET | `/api/feed?limit=&cursor=&direction=&min_impact=` | Лента | `FeedResponse` |
| GET | `/api/brief` | 3 события для роли | `Brief` |
| GET | `/api/insights/{insight_id}` | Инсайт | `InsightDetailResponse` |
| GET | `/api/events/{event_id}/insight` | Инсайт по событию | `InsightDetailResponse`, или 404 `insight_not_ready` с `details.run_id` |
| POST | `/api/events/{event_id}/insight` | Сгенерировать по событию | `GenerateResponse` (200 — готов, 202 — запущен) |
| GET | `/api/insights/{insight_id}/trace` | Трасса | `TraceResponse` |
| POST | `/api/insights/{insight_id}/feedback` | Оценка | `FeedbackOut` |
| POST | `/api/analyze` | Фича B | 202 `RunRef` |
| GET | `/api/analyze/history?limit=` | Мои проверки | `list[AnalyzeHistoryItem]` |
| GET | `/api/runs/{run_id}` | Статус прогона | `RunInfo` |
| GET | `/api/runs/{run_id}/events` | **SSE** шагов прогона | поток (§5) |
| POST | `/api/insights/{insight_id}/chat` | Вопрос в чат | 202 `ChatStartResponse` |
| GET | `/api/insights/{insight_id}/chat?thread_id=` | История чата | `ChatThreadResponse` |
| GET | `/api/sources/{source_id:path}` | Источник | `SourceDetail` |
| GET | `/api/macro` | Ставка и курсы | `MacroResponse` |
| GET | `/api/quality` | Метрики качества и бюджета | `QualityResponse` (`12-quality.md` §6); `offline` — `OfflineSummary`: сводка `eval/reports/latest.json` (источник разметки, nDCG@5 и P@5 по вариантам `ours`, `industry_only`, `no_payments`, `random`, показатели генерации и фичи B) или `null` |
| POST | `/api/ui-events` | Телеметрия интерфейса | 204 |
| POST | `/api/leads` | Заявка на продукт (имитация) | `LeadOut` |
| POST | `/api/admin/ingest/run` | Сбор + тик конвейера сейчас | `{started: true}` |
| POST | `/api/admin/rank/run` | Пересчитать ранжирование | `{rows: int}` |
| POST | `/api/admin/precompute/run` | Прекомпьют (`{companies?, top_k?}`) | `{queued: int}` |
| GET | `/api/admin/review-queue` | Инсайты `needs_review` | `list[ReviewItem]` |
| POST | `/api/admin/insights/{insight_id}/review` | `{status: published\|rejected, note?}` | `ReviewItem` |
| GET | `/api/admin/sources/status` | Состояние RSS-источников | `dict[str, SourceStatus]` |

## 4. Модели запросов и ответов (`api/schemas.py`)

### 4.1 Система и сессия

```python
BudgetMode = Literal["normal", "economy", "exhausted"]

class MetaResponse(BaseModel):
    version: str; demo_mode: bool; llm_mode: Literal["live", "replay", "fake"]
    data_profile: Literal["real", "synthetic"]; budget_mode: BudgetMode
    roles: list[RoleInfo]                     # [{id, name, short}]

class ReadyResponse(BaseModel):
    ready: bool; checks: dict[str, bool]      # sqlite, duckdb, migrations, profiles, taxonomy

class CompanySummary(BaseModel):
    company_id: str; name: str; industry_id: str; industry_name: str
    region_name: str | None; revenue_bucket: str; is_demo: bool
    story: str | None; default_role: Role

class SessionCreate(BaseModel):
    company_id: str; role: Role; jury_code: str | None = None

class SessionUpdate(BaseModel):
    role: Role

class SessionInfo(BaseModel):
    company: CompanySummary; role: Role; jury: bool; demo_mode: bool; budget_mode: BudgetMode

class RefItem(BaseModel):
    id: str; name: str

class ReferenceResponse(BaseModel):            # публичный, кешируется клиентом бессрочно
    version: str                               # сумма версий справочников
    industries: list[RefItem]; factors: list[RefItem]; countries: list[RefItem]
    event_types: list[RefItem]; roles: list[RoleInfo]
    products: list[RefItem]; products_disclaimer: str
```

### 4.2 Профиль

```python
class OverrideOut(BaseModel):
    field: Literal["industry_id", "ved", "products", "notes"]; value: Any; updated_at: datetime

class ProfileResponse(BaseModel):
    profile: CompanyProfile                   # 03-data.md §7 (с наложенными правками)
    overrides: list[OverrideOut]

class CounterpartyOut(BaseModel):
    name: str; industry_id: str; industry_name: str; share: float

class CounterpartiesResponse(BaseModel):
    direction: Literal["suppliers", "buyers"]; coverage: float; basis: str
    mix: list[IndustryShare]; items: list[CounterpartyOut]

class VedOverride(BaseModel):
    country_iso2: str; direction: Literal["import", "export", "unknown"]

class OverridesUpdate(BaseModel):
    industry_id: str | None = None
    ved: list[VedOverride] | None = None
    products: dict[str, bool] | None = None
    notes: str | None = Field(default=None, max_length=1000)
    reset: list[Literal["industry_id", "ved", "products", "notes"]] = []
```

Поле со значением `None` не меняется. Поля из `reset` удаляются. После сохранения: `ProfileStore.invalidate` и `RankingService.rank_company`.

### 4.3 Лента и брифинг

```python
class FeedItem(BaseModel):
    event_id: int
    status: Literal["ready", "pending", "generating", "failed"]
    insight_id: str | None
    run_id: str | None                        # для generating
    headline: str                             # из инсайта, иначе заголовок события
    why_you: str | None                       # из инсайта, иначе chain_preview
    chain_preview: str | None
    direction: Direction
    impact_level: ImpactLevel
    score: float
    confidence_level: Level | None
    event_title: str
    event_type: str
    published_at: datetime                    # events.first_seen_at
    publishers: list[str]
    source_count: int
    stale: bool                               # инсайт построен по старой версии профиля
    needs_review: bool

class FeedResponse(BaseModel):
    items: list[FeedItem]; next_cursor: str | None; total: int
    generated_at: datetime; budget_mode: BudgetMode
```

Порядок — `rankings.score DESC` для `(company, role)` из сессии, с фильтрами `feed.min_score` и `feed.min_relevance`. Статус: `ready`, если есть инсайт текущей `prompt_version` (при старой `profile_version` — `ready` и `stale=true`); `generating`, если есть прогон `queued` или `running`; `failed`, если последний прогон упал, а инсайта нет; иначе `pending`. Курсор — base64 от смещения.

`Brief` — `08-agent.md` §14.

### 4.4 Инсайты, генерация, трасса, обратная связь

```python
class FeedbackIn(BaseModel):
    useful: bool
    reason: Literal["not_relevant", "already_known", "wrong_facts", "too_generic", "unclear",
                    "useful_action", "useful_risk", "other"] | None = None
    comment: str | None = Field(default=None, max_length=500)

class FeedbackOut(FeedbackIn):
    created_at: datetime

class InsightDetailResponse(BaseModel):
    insight: Insight                          # 08-agent.md §8.2
    my_feedback: FeedbackOut | None
    stale: bool

class GenerateResponse(BaseModel):
    status: Literal["ready", "started", "running"]
    insight_id: str | None; run_id: str | None

class RunRef(BaseModel):
    run_id: str

class RunInfo(BaseModel):
    id: str; kind: str; mode: str; status: str
    event_id: int | None; insight_id: str | None; message_id: int | None
    error_code: str | None; error_message: str | None
    created_at: datetime; started_at: datetime | None; finished_at: datetime | None
    duration_ms: int | None; cost_rub: float

class TraceEventOut(BaseModel):
    seq: int; ts: datetime; type: str; phase: str; title: str
    status: Literal["ok", "warn", "error", "info"]; payload: dict[str, Any]
    model: str | None; tokens_in: int | None; tokens_out: int | None
    cost_rub: float | None; latency_ms: int | None

class TraceResponse(BaseModel):
    run: RunInfo; events: list[TraceEventOut]
```

`POST /api/events/{id}/insight`: если готовый инсайт текущих версий есть → `200 {status: ready, insight_id}`. Если прогон по паре уже идёт → `202 {status: running, run_id}`. Иначе запускается `kind=insight`, `mode=pipeline`, `priority=interactive` → `202 {status: started, run_id}`. Событие должно быть публичным или принадлежать компании сессии.

### 4.5 Фича B

```python
class AnalyzeHistoryItem(BaseModel):
    run_id: str; created_at: datetime; status: str
    input_label: str                          # домен URL или первые 80 символов текста
    insight_id: str | None; headline: str | None
```

Тело `POST /api/analyze` — `AnalyzeInput` (`08-agent.md` §12). Ошибки валидации (оба поля или ни одного; текст короче 200 символов) — `422`. Ошибки загрузки и извлечения приходят **в SSE** как `run.failed`, а не HTTP-кодом. Небезопасный URL отсекается сразу: `400 blocked_url`.

### 4.6 Чат

```python
class ChatIn(BaseModel):
    message: str = Field(min_length=2, max_length=1000)
    thread_id: str | None = None

class ChatStartResponse(BaseModel):
    run_id: str; thread_id: str; user_message_id: int

class ChatMessageOut(BaseModel):
    id: int; role: Literal["user", "assistant"]
    text: str | None                          # для user
    answer: ChatAnswer | None                 # для assistant; refs = source_id
    sources: list[SourceRef]
    created_at: datetime

class ChatThreadResponse(BaseModel):
    thread_id: str | None; messages: list[ChatMessageOut]
```

Без `thread_id` создаётся новый тред `thr_<ulid>`. `GET` без `thread_id` возвращает последний тред сессии по этому инсайту.

### 4.7 Источники, макро, телеметрия, заявки

```python
class SourceDetail(BaseModel):
    id: str; kind: SourceKind; title: str; publisher: str | None; url: str | None
    published_at: datetime | None
    excerpt: str
    text: str | None                          # news: тело ≤ 4000; alfa: текст чанка; user_input: текст
    doc_title: str | None; page: int | None   # для alfa
    data: dict[str, Any] | None               # для cbr (ряд) и client_data (доли, контрагенты)

class MacroResponse(BaseModel):
    key_rate: MacroSummary; fx: list[MacroSummary]; updated_at: datetime

class UiEventIn(BaseModel):
    type: Literal["feed_view", "insight_open", "source_open", "trace_open", "chat_open",
                  "brief_view", "analyze_submit", "product_open"]
    insight_id: str | None = None
    payload: dict[str, Any] = {}

class LeadIn(BaseModel):
    product_id: str; insight_id: str | None = None
    comment: str | None = Field(default=None, max_length=500)
    confirm: Literal[True]                    # без явного подтверждения → 422

class LeadOut(BaseModel):
    id: int; product_name: str; message: str  # «Демо: заявка сохранена, в реальном сервисе с вами свяжется менеджер»
```

### 4.8 Пример `FeedItem`

```json
{"event_id": 123, "status": "ready", "insight_id": "ins_01JB…", "run_id": null,
 "headline": "Арматура дорожает: себестоимость ваших объектов может вырасти",
 "why_you": "34% ваших закупок — металлургия",
 "chain_preview": "Металлурги поднимают цены на арматуру → 34% ваших закупок — металлургия → риск: рост закупочных цен → себестоимость",
 "direction": "risk", "impact_level": "high", "score": 0.428, "confidence_level": "high",
 "event_title": "Металлурги поднимают цены на арматуру на 8% с ноября", "event_type": "commodity_prices",
 "published_at": "2026-10-22T06:10:00Z", "publishers": ["Интерфакс", "Коммерсантъ"], "source_count": 2,
 "stale": false, "needs_review": false}
```

## 5. SSE: `GET /api/runs/{run_id}/events` (`api/sse.py`)

- Реализация — `sse_starlette.EventSourceResponse`, `ping=15`. Заголовки: `Cache-Control: no-cache`, `X-Accel-Buffering: no`. В nginx для `/api/` отключена буферизация (`13-deploy-demo.md` §3).
- Доступ: прогон должен принадлежать компании сессии.
- Алгоритм:
  1. `last = int(Last-Event-ID или 0)`.
  2. Цикл: прочитать `trace_events WHERE run_id=? AND seq > last ORDER BY seq` (в `asyncio.to_thread`) и отправить каждое событие.
  3. Если прогон в конечном статусе и новых событий нет — отправить `end` и закрыть поток.
  4. Если клиент отключился — выйти.
  5. Иначе `await asyncio.sleep(0.25)`.
- Максимальная длительность потока — 5 минут. Для завершённого прогона история отдаётся сразу, вместе с `end`.

```
id: 7
event: trace
data: {"seq":7,"ts":"2026-10-22T10:00:01.200Z","type":"tool.result","phase":"tools","title":"34% закупок — металлургия; 3 пути влияния","status":"ok","payload":{"tool":"compute_exposure","eids":["E4","E5","E6"],"duration_ms":38,"ok":true},"model":null,"tokens_in":null,"tokens_out":null,"cost_rub":null,"latency_ms":38}

event: end
data: {"status":"succeeded","insight_id":"ins_01JB…","message_id":null,"error_code":null,"error_message":null,"duration_ms":17340,"cost_rub":0.84}
```

На клиенте обычный `EventSource` (cookie уходит автоматически, тот же origin) и два слушателя: `trace` и `end`. При обрыве браузер сам переподключается с `Last-Event-ID`.

## 6. Ошибки (`api/errors.py`)

Формат ответа об ошибке единый:

```json
{"error": {"code": "not_found", "message": "Инсайт не найден", "details": {}}}
```

| HTTP | code | Когда |
|---|---|---|
| 400 | `bad_request`, `blocked_url` | Некорректный запрос; небезопасный URL |
| 401 | `unauthorized` | Нет или испорчена сессия |
| 403 | `forbidden` | Нет прав (админка, jury-код) |
| 404 | `not_found`, `insight_not_ready` | Объекта нет или он чужой; инсайт ещё не готов (`details.run_id`) |
| 409 | `conflict` | Конкурентное изменение |
| 422 | `validation_error` | Ошибка валидации (`details.errors` — список Pydantic) |
| 429 | `rate_limited`, `busy` | Лимит частоты (`Retry-After`); занято слишком много прогонов |
| 503 | `budget_exhausted`, `not_ready` | Бюджет исчерпан при запуске прогона; сервис не готов |
| 500 | `internal` | Прочее (без стектрейса в ответе) |

Доменные исключения (`errors.py`: `NotFoundError`, `ForbiddenError`, `BudgetExceeded`, `RateLimited`, `BlockedUrl`, …) переводятся в коды обработчиками в `api/errors.py`. `RequestValidationError` от FastAPI тоже приводится к этому формату.

## 7. Лимиты частоты (`api/ratelimit.py`)

Токен-бакет в памяти процесса, ключ — `sid` сессии (для `POST /api/session` — IP).

| Эндпоинт | Лимит |
|---|---|
| `POST /api/analyze` | 6 в минуту, 60 в сутки |
| `POST /api/events/{id}/insight` | 10 в минуту |
| `POST /api/insights/{id}/chat` | 15 в минуту, 200 в сутки |
| `POST /api/session` | 20 в минуту на IP |
| `POST /api/insights/{id}/feedback`, `/api/ui-events`, `/api/leads` | 60 в минуту |

Кроме того, одновременных интерактивных прогонов не больше `AGENT_MAX_CONCURRENT_RUNS` (4) на весь процесс. Сверх лимита — `429 busy`.

## 8. OpenAPI и клиент

- `alfa api openapi --out frontend/openapi.json` — выгрузка `app.openapi()` без запуска сервера (`make openapi`).
- Фронтенд: `openapi-typescript openapi.json -o src/api/schema.d.ts` и `openapi-fetch`: `createClient<paths>({ baseUrl: "" })`. Пути в схеме уже содержат `/api`.
- Swagger UI доступен на `/api/docs`, схема — на `/api/openapi.json`. В README есть ссылка на них (требование сдачи: OpenAPI).
- CI проверяет, что `frontend/openapi.json` совпадает с выгрузкой из кода (`13-deploy-demo.md` §5).
