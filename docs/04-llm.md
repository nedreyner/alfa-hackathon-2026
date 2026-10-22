# 04. LLM-слой: шлюз, модели, структурированный вывод, кеш, бюджет

## 1. Шлюз и допущения

- Шлюз хакатона совместим с OpenAI Chat Completions: `POST {base}/chat/completions`, `GET {base}/models`. Авторизация `Authorization: Bearer <LLM_API_KEY>` (допущение A2).
- Есть основной адрес `LLM_BASE_URL` и запасной `LLM_BASE_URL_FALLBACK` (для российских хостингов). У обоих путь заканчивается на `/v1`.
- Используем только Chat Completions через `openai.AsyncOpenAI(base_url=..., api_key=..., max_retries=0, timeout=...)`. Responses API, Assistants и Batch не используем: шлюзы их обычно не поддерживают.
- Точные имена моделей, цены и поддержка tools, `json_schema`, vision и стриминга неизвестны (A3). Их определяет `alfa llm probe` (§3), результат вносится в `config/models.yaml`.

## 2. Модели и задачи

| Модель (ключ в конфиге) | Назначение | Почему она |
|---|---|---|
| `gemma` — Gemma 4 26B | Массовая разметка новостей (`tagging`), переранжирование (`rerank`) | Самая дешёвая, задача классификационная |
| `qwen_text` — Qwen3.6 35B | Извлечение фактов, прогнозов и позиций из PDF (`research_extract`); запасная для разметки и проверки | Сильная в извлечении структуры из русского текста |
| `deepseek` — DeepSeek-V4.1-Flash | Агент (`agent`), черновик (`draft`), доработка (`revise`) | Главная модель рассуждений, контекст 1 млн токенов, быстрая |
| `glm` — GLM-5.3-Flash | Проверка (`verify`) | Другое семейство даёт независимую проверку |
| `kimi` — Kimi-K2.6 | Чат (`chat`); запасная для агента | Хорошо ведёт диалог, длинный контекст |
| `qwen_vl` — Qwen3-VL | Графики и таблицы в PDF (`vision`) | Единственная мультимодальная |

### 2.1 `config/models.yaml`

```yaml
version: 1
gateway:
  timeout_s: 60
  connect_timeout_s: 10
  max_concurrency_interactive: 4
  max_concurrency_background: 2
  retries: 2
  token_param: max_tokens            # max_tokens | max_completion_tokens — по результату probe
default_price_rub_per_1m: {input: 50, output: 200}   # консервативно, пока нет реальных цен
models:
  gemma:     {id: "gemma-4-26b",         family: gemma,    context_tokens: 128000,  price_rub_per_1m: {input: null, output: null},
              capabilities: {tools: null, json_schema: null, json_object: null, vision: false, usage: null}}
  qwen_text: {id: "qwen3.6-35b",         family: qwen,     context_tokens: 128000,  price_rub_per_1m: {input: null, output: null}, capabilities: {}}
  deepseek:  {id: "deepseek-v4.1-flash", family: deepseek, context_tokens: 1000000, price_rub_per_1m: {input: null, output: null}, capabilities: {}}
  glm:       {id: "glm-5.3-flash",       family: glm,      context_tokens: 128000,  price_rub_per_1m: {input: null, output: null}, capabilities: {}}
  kimi:      {id: "kimi-k2.6",           family: kimi,     context_tokens: 256000,  price_rub_per_1m: {input: null, output: null}, capabilities: {}}
  qwen_vl:   {id: "qwen3-vl",            family: qwen,     context_tokens: 32000,   price_rub_per_1m: {input: null, output: null},
              capabilities: {vision: true}}
tasks:
  tagging:             {chain: [gemma, qwen_text],    temperature: 0,   max_tokens: 1200, priority: background,  strategy: auto,      timeout_s: 30}
  tagging_interactive: {chain: [gemma, qwen_text],    temperature: 0,   max_tokens: 1200, priority: interactive, strategy: auto,      timeout_s: 20}
  research_extract:    {chain: [qwen_text, deepseek], temperature: 0,   max_tokens: 2000, priority: background,  strategy: auto,      timeout_s: 60}
  vision:              {chain: [qwen_vl],             temperature: 0,   max_tokens: 1500, priority: background,  strategy: json_object, timeout_s: 90}
  rerank:              {chain: [gemma, qwen_text],    temperature: 0,   max_tokens: 800,  priority: precompute,  strategy: auto,      timeout_s: 30}
  agent:               {chain: [deepseek, kimi],      temperature: 0.2, max_tokens: 4000, priority: interactive, strategy: tool_call, timeout_s: 45}
  draft:               {chain: [deepseek, kimi],      temperature: 0.2, max_tokens: 4000, priority: precompute,  strategy: auto,      timeout_s: 45}
  revise:              {chain: [deepseek, kimi],      temperature: 0.1, max_tokens: 4000, priority: precompute,  strategy: auto,      timeout_s: 45}
  verify:              {chain: [glm, qwen_text],      temperature: 0,   max_tokens: 2000, priority: precompute,  strategy: auto,      timeout_s: 40,
                        exclude_drafter_family: true}
  chat:                {chain: [kimi, deepseek],      temperature: 0.3, max_tokens: 1500, priority: interactive, strategy: tool_call, timeout_s: 30}
```

- `priority` в задаче — значение по умолчанию. Вызывающий код может его поднять: например, `draft` внутри интерактивного прогона идёт с `interactive`.
- `exclude_drafter_family: true`: проверку нельзя делать моделью того же семейства, что писала черновик. Если черновик написала `kimi` (запасная), `glm` подходит. Если цепочка после исключения пуста — ошибка конфигурации на старте.
- `null` в ценах означает «использовать `default_price_rub_per_1m`» с предупреждением в лог при старте.

## 3. Probe (`alfa llm probe`)

Команда (модуль `llm/probe.py`) делает следующее:

1. `GET /models` по обоим адресам. Печатает список и сверяет с `models.*.id`. При расхождении подсказывает похожие имена (`difflib.get_close_matches`).
2. Для каждой модели из конфига запускает 5 коротких тестов, суммарно меньше 3 тыс. токенов на модель:
   - `basic`: «Ответь одним словом: ок» → задержка, наличие `usage`.
   - `tools`: инструмент `get_time(city)` с принудительным `tool_choice` → вернулись ли `tool_calls` с валидным JSON.
   - `json_schema`: `response_format={"type":"json_schema",...}` со схемой `{answer: string}` → валидность.
   - `json_object`: `response_format={"type":"json_object"}`.
   - `vision` (только при `capabilities.vision=true`): картинка 64×32 с напечатанным числом «42», вопрос — какое число.
   - Попутно: какое имя параметра лимита принимается (`max_tokens` или `max_completion_tokens`). Определяется по ошибке 400.
3. Пишет `data/runtime/model_capabilities.json` и печатает таблицу «модель × тест». Если ответ содержит стоимость (`usage.cost` или заголовок со стоимостью), печатает её.
4. `--write-config` переносит найденные `capabilities` и `token_param` в `config/models.yaml` (цены команда вносит руками по документации шлюза).

`LLMRouter` при старте объединяет `capabilities` из YAML и `model_capabilities.json`; при конфликте приоритет у файла probe.

## 4. Интерфейсы

```python
# llm/types.py
from typing import Literal, Any, Generic, TypeVar
from pydantic import BaseModel

Priority = Literal["interactive", "precompute", "background"]
TaskName = Literal["tagging", "tagging_interactive", "research_extract", "vision", "rerank",
                   "agent", "draft", "revise", "verify", "chat"]
Strategy = Literal["auto", "tool_call", "json_schema", "json_object", "prompt_only"]

class ImagePart(BaseModel):
    type: Literal["image_url"] = "image_url"
    image_url: dict[str, str]                      # {"url": "data:image/png;base64,..."}

class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str

class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]                       # при невалидном JSON: {"__raw__": "<строка>"}

class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[TextPart | ImagePart] | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]                      # JSON Schema (см. §5.3)

class Usage(BaseModel):
    tokens_in: int
    tokens_out: int
    cost_rub: float

class LLMRequest(BaseModel):
    task: TaskName
    messages: list[Message]
    prompt_version: str
    tools: list[ToolSpec] | None = None
    tool_choice: Literal["auto", "required", "none"] | dict[str, Any] | None = None
    response_format: dict[str, Any] | None = None
    temperature: float | None = None                # None → из задачи
    max_tokens: int | None = None                   # None → из задачи
    priority: Priority | None = None                # None → из задачи
    run_id: str | None = None
    cache: bool = True
    exclude_families: list[str] = []

class LLMResult(BaseModel):
    model_key: str                                  # ключ из models.yaml
    model_id: str
    family: str
    content: str | None
    tool_calls: list[ToolCall]
    finish_reason: str | None
    usage: Usage
    cached: bool
    latency_ms: int
    base_url_kind: Literal["primary", "fallback"] | None
    fallback_model_used: bool

T = TypeVar("T", bound=BaseModel)

class StructuredResult(BaseModel, Generic[T]):
    value: T
    raw: LLMResult
    strategy_used: Strategy
    repaired: bool
```

```python
# llm/client.py — единственное место, где импортируется openai
class GatewayClient:
    def __init__(self, primary_url: str, fallback_url: str | None, api_key: str,
                 timeout_s: float, connect_timeout_s: float, token_param: str) -> None: ...
    async def chat(self, model_id: str, payload: dict[str, Any], timeout_s: float
                   ) -> tuple[dict[str, Any], Literal["primary", "fallback"]]: ...
    async def list_models(self) -> dict[Literal["primary", "fallback"], list[str]]: ...

# llm/router.py
class LLMRouter:
    def __init__(self, config: ModelsConfig, backend: "LLMBackend", cache: LLMCache,
                 budget: BudgetGuard, on_call: Callable[[LLMCallRecord], None] | None = None) -> None: ...
    async def complete(self, req: LLMRequest) -> LLMResult: ...
    async def structured(self, *, task: TaskName, messages: list[Message], schema: type[T],
                         prompt_version: str, priority: Priority | None = None,
                         run_id: str | None = None, strategy: Strategy | None = None,
                         exclude_families: list[str] = [], cache: bool = True) -> StructuredResult[T]: ...
    def capabilities(self, model_key: str) -> ModelCapabilities: ...
    def chain(self, task: TaskName, exclude_families: list[str] = []) -> list[ModelConfig]: ...

# Бэкенды: LiveBackend (GatewayClient), ReplayBackend (только кеш), FakeBackend (llm/fake.py)
class LLMBackend(Protocol):
    async def call(self, model: ModelConfig, payload: dict[str, Any], timeout_s: float
                   ) -> tuple[dict[str, Any], Literal["primary", "fallback"] | None]: ...
```

`get_router()` в `llm/__init__.py` собирает роутер по настройкам (`LLM_MODE`) один раз на процесс. В тестах роутер подменяется фикстурой.

**Алгоритм `complete`:**

1. Заполнить умолчания из задачи (`temperature`, `max_tokens`, `priority`).
2. Если `cache=True`, вычислить ключ (§6) и поискать в кеше. При попадании вернуть результат с `cached=True`, увеличить `hits` и записать `llm_calls(cached=1, cost=0)`.
3. Для каждой модели цепочки (с учётом `exclude_families`):
   1. Оценить стоимость (§7.3) и вызвать `budget.check(priority, est, run_id)`. При `BudgetExceeded` прервать без перехода к следующей модели.
   2. Собрать payload: `model`, `messages`, `tools` (`[{"type":"function","function":{...}}]`), `tool_choice`, `response_format`, `temperature`, параметр лимита из `token_param`.
   3. Вызвать бэкенд под семафором приоритета (interactive: 4, остальные: 2) с ретраями (§8).
   4. Успех: разобрать ответ в `LLMResult`, посчитать стоимость, записать `llm_calls`, положить в кеш, вернуть.
   5. Исчерпаны ретраи: записать `llm_calls(status=error)` и перейти к следующей модели.
4. Все модели упали → `LLMUnavailable`.

## 5. Структурированный вывод

### 5.1 Стратегии

| Стратегия | Как просим | Как разбираем | Когда |
|---|---|---|---|
| `tool_call` | Один инструмент `submit_<schema>` с `parameters = схема`; `tool_choice={"type":"function","function":{"name":"submit_<schema>"}}` | `tool_calls[0].arguments` → `schema.model_validate` | Модель поддерживает tools (по probe) |
| `json_schema` | `response_format={"type":"json_schema","json_schema":{"name":…, "schema":…, "strict": false}}` | `json.loads(content)` → validate | Есть `json_schema`, нет tools |
| `json_object` | `response_format={"type":"json_object"}` + схема в конце system-промпта | то же | Есть только `json_object` |
| `prompt_only` | Схема и пример в промпте, «верни только JSON» | Первый сбалансированный блок `{…}` из текста → validate | Ничего не поддерживается |

`auto` выбирает первую доступную в порядке `tool_call → json_schema → json_object → prompt_only`. Неизвестная (`null`) возможность считается недоступной.

### 5.2 Починка

При ошибке JSON или `ValidationError` делается **одна** попытка починки на той же модели. К сообщениям добавляются `assistant` (сырой ответ) и `user`:

> Ответ не прошёл проверку схемы. Ошибки:
> {список ошибок Pydantic, не более 20 строк: путь — сообщение}
> Верни исправленный объект целиком, без пояснений.

Вторая неудача → `llm_calls(status=invalid_output)` → следующая модель цепочки. Если упали все модели → `LLMInvalidOutput`.

### 5.3 JSON Schema для моделей (`llm/structured.py: to_llm_schema`)

`model_json_schema()` у Pydantic даёт конструкции, которые ломают часть провайдеров. Преобразование:

- раскрыть все `$ref` и `$defs` (инлайн);
- `anyOf: [X, {"type":"null"}]` → `X` с `"type": [X.type, "null"]`;
- `Literal` → `enum`, удалить `title` и `default: null`;
- оставить `description` из `Field(description=...)`: это подсказки модели;
- добавить `additionalProperties: false` для объектов;
- `max_length` и `min_length` у списков → `maxItems` и `minItems`, у строк → `maxLength` (провайдеры часто это игнорируют, финальная проверка — Pydantic).

Компактная форма схемы для промптов (`json_object` и `prompt_only`) — `schema_to_prompt(schema)`: TypeScript-подобная запись, она короче JSON Schema примерно в 3 раза.

## 6. Кеш (`llm/cache.py`, таблица `llm_cache`)

**Ключ:** `sha256` от канонического JSON (сортированные ключи, без пробелов):

```json
{"v": 1, "task": "...", "chain": ["deepseek","kimi"], "prompt_version": "...",
 "messages": [...], "tools": [...], "tool_choice": ..., "response_format": ...,
 "temperature": 0.2, "max_tokens": 4000}
```

Ключ не содержит конкретную модель: ответ любой модели цепочки заполняет одну запись. Так replay детерминирован, даже если в живом прогоне сработала запасная модель.

**Правила:**

- Кешируются все задачи, кроме `chat` (`cache=False` по умолчанию). При temperature > 0 кеш тоже включён: воспроизводимость демо важнее разнообразия.
- Срок жизни бессрочный. Инвалидация — только сменой `prompt_version` или версии справочников: разметка включает `taxonomy_version` в `prompt_version`, например `tagging_v1+tx1`.
- `alfa llm cache stats|clear --task X|export --runs <ids> --out file.jsonl|import file.jsonl`.

## 7. Бюджет (`llm/budget.py`, таблица `llm_calls`)

### 7.1 Параметры

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `LLM_DAILY_BUDGET_RUB` | 450 | Жёсткий суточный лимит. Это меньше 500 ₽ с запасом на неточность оценки |
| `LLM_INTERACTIVE_RESERVE_RUB` | 150 | Последние 150 ₽ суток доступны только интерактивным вызовам |
| `LLM_MAX_RUN_COST_RUB` | 5 | Лимит на один прогон агента |
| `BUDGET_TZ` | Europe/Moscow | Граница суток |

### 7.2 Правила

- `spent = SUM(cost_rub) FROM llm_calls WHERE budget_day = today AND cached = 0`. Значение кешируется в памяти на 5 секунд и сбрасывается после каждой записи.
- `background` и `precompute` разрешены, если `spent + est ≤ limit − reserve`.
- `interactive` разрешён, если `spent + est ≤ limit`.
- В прогоне: `run_cost + est ≤ LLM_MAX_RUN_COST_RUB`, иначе `BudgetExceeded(scope="run")`. Агент пытается завершить прогон без лишних шагов (§8 в `08-agent.md`).
- Режим бюджета для интерфейса: `normal` (spent < limit − reserve), `economy` (< limit), `exhausted`.
- Фактическая стоимость = `tokens_in × p_in + tokens_out × p_out` (за 1 млн). Если шлюз вернул стоимость в ответе, берём её.

### 7.3 Оценка до вызова

`tokens_in_est = ceil(len(всех текстов сообщений и схем) / 3)`, `tokens_out_est = 0.5 × max_tokens`, `est = tokens_in_est × p_in + tokens_out_est × p_out`. Оценка намеренно консервативная.

### 7.4 Сколько можно за сутки

Пусть `p_in`, `p_out` — цены в ₽ за 1 млн токенов. Типичные объёмы:

| Операция | Вход, ток. | Выход, ток. | Количество в сутки |
|---|---|---|---|
| Разметка новости | 2 500 (с промптом справочников) | 400 | `N_tag` ≈ 200–400 после префильтра |
| Инсайт в режиме pipeline: draft + verify | 9 000 + 5 000 | 1 800 + 800 | `N_ins` ≈ 30–60 (6 демо-компаний × top-5, обновления) |
| Фича B, режим agentic: intake + 2 раунда + verify | 2 500 + 2 × 9 000 + 5 000 | 400 + 2 200 + 800 | `N_B` ≈ 20–50 (жюри и тесты) |
| Чат | 6 000 × 2 раунда | 600 | `N_chat` ≈ 30 |

`Cost/день ≈ [N_tag·(2.5k·p_in + 0.4k·p_out) + N_ins·(14k·p_in + 2.6k·p_out) + N_B·(25.5k·p_in + 3.4k·p_out) + N_chat·(12k·p_in + 0.6k·p_out)] / 10⁶`

Пример при гипотетических ценах `p_in = 20 ₽`, `p_out = 80 ₽`: разметка 300 → 24 ₽; инсайты 60 → 29 ₽; фича B 40 → 31 ₽; чат 30 → 8 ₽. Итого ≈ 92 ₽ в сутки. Если цены в 4 раза выше, выходит ≈ 370 ₽: укладываемся только с префильтром и прекомпьютом только для демо-компаний. **После T1.10 этот расчёт повторяется на реальных ценах**, а итог записывается в README.

Рычаги экономии по порядку: строже префильтр → меньше `top_k` в прекомпьюте → разметка заголовка и лида вместо полного текста (`TAG_BODY_CHARS=1500`) → отключение LLM-реранка → отказ от LLM-судьи для инсайтов с уверенностью ≥ 0.8 по детерминированным проверкам (флаг `VERIFY_LLM_SKIP_IF_CLEAN`).

## 8. Надёжность

- **Таймауты:** `timeout_s` из задачи, соединение — `connect_timeout_s`.
- **Ретраи** (на модель): 429, 5xx, таймаут, обрыв соединения. До `retries=2` попыток с задержкой 1 с и 3 с (±20% случайно). Для 429 учитывается `Retry-After` (не больше 10 с).
- **Запасной адрес:** при ошибке соединения или 502/503/504 на основном адресе сразу (без задержки) пробуем тот же запрос на `LLM_BASE_URL_FALLBACK`. Если запасной адрес отвечает успешно 3 раза подряд, а основной падает, переключаемся на запасной на 10 минут (`kv:llm_active_base`).
- **Не ретраим** 400 и 422 (ошибка запроса). Только для `token_param` один повтор с другим именем параметра, затем запоминаем выбор.
- **Конкурентность:** семафоры по приоритету (§2.1), чтобы фоновые задачи не съели канал для интерактива.
- **Исключения** (`alfa_insight/errors.py`): `LLMUnavailable`, `LLMInvalidOutput`, `BudgetExceeded(scope: "day" | "reserve" | "run")`, `LLMReplayMiss`. Все наследуют `LLMError`.

## 9. Режимы (`LLM_MODE`)

| Режим | Бэкенд | Кеш | Для чего |
|---|---|---|---|
| `live` | `LiveBackend` (шлюз) | чтение и запись | Обычная работа |
| `replay` | `ReplayBackend` | только чтение; промах → `LLMReplayMiss` | Демо без сети, детерминированные тесты на записанных ответах |
| `fake` | `FakeBackend` | не используется | Тесты, разработка интерфейса без бюджета |

**FakeBackend** (`llm/fake.py`) — детерминированные, валидные по схеме ответы на основе эвристик. По ним можно прогнать всю систему офлайн:

| Задача | Поведение |
|---|---|
| `tagging` | Отрасли по совпадению лемм заголовка и текста с `keywords` (до 3, `impact` по числу совпадений), факторы по словарю префильтра (ставка → `key_rate`, «юань» → `fx_cny`, «пошлин» → `customs_tariffs`, …), `event_type` по правилам на ключевые слова, `importance` = 2 + наличие чисел + доверие источника, `summary` = первое предложение |
| `research_extract` | Предложения с «ожидаем», «прогноз», «полагаем» → `forecast` или `position`, с числами → `fact` |
| `vision` | `{"description": "fake: описание графика недоступно", "data_points": []}` |
| `rerank` | Релевантность = округлённый базовый скор × 3 |
| `agent` | Первый вызов возвращает `tool_calls`: `search_alfa_research(query=заголовок)` и, если в событии есть `key_rate` или `fx_*`, `get_macro`. Второй вызов — `submit_insight` с черновиком по шаблону из evidence (см. ниже) |
| `draft`, `revise` | Шаблонный `InsightDraft`: факты из evidence `news:*` (первое предложение, ссылка на E-id), «почему вам» из путей `compute_exposure`, последствия по направлению путей, действие — из кандидатов продуктов, позиция банка из evidence `alfa:*` |
| `verify` | Все утверждения `supported`, кроме тех, где в тексте есть маркер `[[UNSUPPORTED]]` (для тестов отрицательных сценариев) |
| `chat` | `submit_answer` с одним блоком `ai`, ссылкой на первый evidence и двумя follow-up |

Фейковые ответы помечаются `model_key="fake"`, а в UI видна плашка «демо-режим без LLM».

## 10. Промпты: хранение и рендер

- Шаблоны Jinja2 лежат в `backend/alfa_insight/prompts/`. Реестр — `prompts/registry.yaml`:

```yaml
tagging:          {version: tagging_v1,          system: tagging.system.j2,          user: tagging.user.j2}
research_extract: {version: research_extract_v1, system: research_extract.system.j2, user: research_extract.user.j2}
vision:           {version: vision_v1,           system: vision.system.j2,           user: vision.user.j2}
rerank:           {version: rerank_v1,           system: rerank.system.j2,           user: rerank.user.j2}
agent:            {version: agent_v1,            system: agent.system.j2,            user: agent.user.j2}
draft:            {version: draft_v1,            system: agent.system.j2,            user: draft.user.j2}
revise:           {version: revise_v1,           system: agent.system.j2,            user: revise.user.j2}
verify:           {version: verify_v1,           system: verify.system.j2,           user: verify.user.j2}
chat:             {version: chat_v1,             system: chat.system.j2,             user: chat.user.j2}
```

- `PromptLoader.render(name, **ctx) -> RenderedPrompt(version: str, messages: list[Message])`. Окружение Jinja2 с `StrictUndefined`, `autoescape=False`, `trim_blocks=True`.
- Общие макросы в `prompts/_macros.j2`: `untrusted(id, text, kind)`, `labels_rules()`, `style_rules()`, `taxonomy_block()`. Тексты — в `05-prompts.md`.
- Фильтр `sanitize_untrusted`: удалить управляющие и невидимые символы (`​-‏`, `⁠-⁯`, `﻿`, теги `\U000e0000-\U000e007f`), экранировать `</untrusted` → `<\/untrusted`, обрезать до лимита символов (по умолчанию 12 000).
- Версия промпта входит в ключ кеша и записывается в `insights.prompt_version`. **Любая правка смысла — новая версия.**

## 11. Учёт и трасса

- Каждый вызов — `LLMCallRecord` → `llm_calls`. Роутер вызывает `on_call(record)`. Агент подписывает на этот хук `TraceWriter`, и в трассе появляются события `llm.call` с моделью, токенами, стоимостью, задержкой, признаком кеша и запасной модели.
- `alfa llm budget` печатает траты сегодня и за 7 дней по задачам и моделям, остаток и режим.
