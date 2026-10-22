# 10. Фронтенд

## 1. Стек

| Пакет | Версия (ориентир, фиксирует lock-файл) | Назначение |
|---|---|---|
| react, react-dom | 19.x | UI |
| typescript | **5.9.x** (не 7.x: openapi-typescript требует `^5`) | Типы |
| vite + @vitejs/plugin-react | актуальная стабильная (8.x; если плагины несовместимы — 7.x) | Сборка и dev-сервер |
| @alfalab/core-components | 50.x (MIT) | Дизайн-система Альфа-Банка |
| @tanstack/react-query | 5.x | Серверное состояние |
| react-router | 7.x | Маршрутизация |
| zustand | 5.x | Небольшой стор сессии и UI |
| @xyflow/react | 12.x | Граф «цепной реакции» |
| recharts | 3.x | Графики на странице качества |
| openapi-fetch / openapi-typescript | 0.17 / 7.x | Типизированный клиент из OpenAPI |
| eslint 9 + typescript-eslint + eslint-plugin-react-hooks, prettier | — | Линт и формат |
| vitest + @testing-library/react + jsdom | — | Тесты |

Если `npm install` ругается на peer-зависимости core-components, явно поставить `@alfalab/core-components-config`. Иконки — встроенные SVG-компоненты из `src/components/common/icons.tsx` (5–10 штук). Внешний пакет иконок добавляется только после проверки его лицензии.

## 2. Структура `frontend/src`

```
main.tsx                       # глобальные стили, монтирование <App/>
app/
  App.tsx                      # QueryClientProvider + RouterProvider
  router.tsx                   # маршруты, lazy-импорты страниц
  queryClient.ts
  session.ts                   # zustand: копия /api/session, флаги баннеров
  RequireSession.tsx           # редирект на /login без сессии
api/
  schema.d.ts                  # генерируется (npm run gen:api), не редактировать
  client.ts                    # openapi-fetch, ApiError, 401 → /login
  hooks.ts                     # useFeed, useBrief, useInsight, … и мутации
  sse.ts                       # useRunEvents
pages/
  LoginPage.tsx  HomePage.tsx  FeedPage.tsx  InsightPage.tsx  TracePage.tsx
  AnalyzePage.tsx  ProfilePage.tsx  QualityPage.tsx  NotFoundPage.tsx
components/
  layout/   AppShell, TopBar, RoleSwitcher, CompanyBadge, ModeBanner
  insight/  InsightCard, DirectionTag, ImpactBadge, ConfidenceBadge, ClaimText, ClaimLabel,
            SourceDrawer, Section, ConsequenceList, ActionList, ProductChip, LeadModal,
            BankViewBlock, ChainGraph, ChainPreview, FeatureChips, FeedbackBar, StatusNotice
  agent/    AgentTimeline, TimelineStep, RunSummary
  chat/     ChatPanel, ChatMessage, FollowupChips
  home/     TodayWidget, AccountsWidget, PaymentsWidget
  profile/  FactsGrid, IndustryMixBar, CounterpartyTable, FactorList, OverridesForm
  quality/  MetricTile, BudgetChart, FeedbackStats, ReviewQueue
  common/   EmptyState, ErrorState, SkeletonCard, RelativeTime, icons
lib/
  labels.ts                    # все русские подписи enum и секций
  format.ts                    # проценты, деньги, даты (ru-RU, Europe/Moscow)
  telemetry.ts                 # sendUiEvent (fire-and-forget)
styles/
  global.css  tokens.css
```

## 3. Подключение core-components

```ts
// main.tsx
import '@alfalab/core-components/vars/bundle/corp.css';   // CSS-переменные палитры корпоративных продуктов (файл есть в пакете)
import './styles/tokens.css';
import './styles/global.css';
```

```ts
import { Button } from '@alfalab/core-components/button';
import { Typography } from '@alfalab/core-components/typography';
```

Импорт всегда по подпути: так в сборку попадает только нужное. Документация компонентов — Storybook `https://core-ds.github.io/core-components/`. Основные компоненты: `Button`, `Typography` (`TitleResponsive`, `Text`), `Tag` / `FilterTag`, `Status`, `Skeleton`, `Spinner`, `SidePanel` / `Drawer`, `Modal`, `Tabs`, `Select`, `Input`, `Textarea`, `Tooltip`, `Plate`, `Divider`, `Gap`, `Collapse`, `Amount`. Точные имена и пропсы проверяются по Storybook в T4.7.

Фирменный шрифт Альфа-Банка не входит в открытый пакет. Используется системный стек (§4).

## 4. Дизайн: Альфа + минимализм Apple

**Принципы:**
- Белый фон, много воздуха, **одна главная мысль на экран**: вывод крупно, объяснение мельче и серым.
- Красный `#EF3124` — **только акцент**: главная кнопка экрана, логотип и точка «важно», критичный риск. Остальное в чёрном и сером.
- Две семантические метки вместо пёстрых тегов: «Риск» и «Возможность». Происхождение утверждения обозначают маленькие бейджи «Факт», «Альфа-Банк», «Вывод ИИ».
- Подробности раскрываются по нажатию, без стен текста.
- Анимации короткие (160–240 мс, `ease-out`): карточки появляются со смещением 8 px, шаги агента — каскадом через 120 мс. Всё отключается при `prefers-reduced-motion`.

**Токены** (`styles/tokens.css`). Значения в `var(...)` — подстановка из core-components, имена переменных проверить в `vars/colors-*.css`:

```css
:root {
  --ai-accent: #EF3124;
  --ai-text: var(--color-light-text-primary, #0E0E10);
  --ai-text-secondary: var(--color-light-text-secondary, #86868A);
  --ai-bg: var(--color-light-bg-primary, #FFFFFF);
  --ai-bg-subtle: var(--color-light-bg-secondary, #F3F4F5);
  --ai-border: #E7E8EB;
  --ai-risk: #D4200C;        --ai-risk-bg: #FDEDEB;
  --ai-opportunity: #0B8F43; --ai-opportunity-bg: #E8F6EE;
  --ai-mixed: #6E6E73;       --ai-mixed-bg: #F1F1F3;
  --ai-radius-lg: 24px; --ai-radius-md: 16px; --ai-radius-sm: 10px;
  --ai-shadow: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06);
  --ai-font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  --ai-content-width: 760px;
}
```

**Типографика:** вывод — 32/40 semibold; заголовок секции — 20/28 semibold; основной текст — 16/24; вторичный — 14/20 серый; подписи — 12/16.

**Метки:**

| Что | Вид |
|---|---|
| `fact` | бейдж «Факт», серая обводка |
| `bank` | бейдж «Альфа-Банк», красный текст на светло-красном фоне |
| `ai` | бейдж «Вывод ИИ», серая заливка; уверенность в подсказке |
| Риск / Возможность / Смешанное | тег с фоном `--ai-risk-bg` / `--ai-opportunity-bg` / `--ai-mixed-bg` и текстом соответствующего цвета |
| Уровень влияния | «Влияние: высокое» и 1–4 точки |
| Уверенность | «Уверенность: высокая», причины в подсказке |

Цвет никогда не единственный носитель смысла: у каждой метки есть текст.

## 5. Маршруты (`app/router.tsx`)

| Путь | Страница | Доступ |
|---|---|---|
| `/login` | LoginPage | без сессии |
| `/` | HomePage (главная Альфа-Бизнеса, макет) | сессия |
| `/feed` | FeedPage | сессия |
| `/insights/:insightId` | InsightPage | сессия |
| `/insights/:insightId/trace` | TracePage (полноэкранная трасса) | сессия |
| `/analyze` | AnalyzePage (фича B) | сессия |
| `/profile` | ProfilePage | сессия |
| `/quality` | QualityPage | сессия |
| `*` | NotFoundPage | — |

Страницы грузятся через `React.lazy`. xyflow и recharts попадают только в чанки тех страниц, где используются.

## 6. Экраны

### 6.1 Вход (`/login`)

- Заголовок «Альфа Инсайт» и подзаголовок «Новости, которые важны вашему бизнесу».
- Карточки демо-компаний из `GET /api/demo/companies`: название, отрасль, регион, выручка, «история» серым.
- Выбор роли: сегментированный переключатель «Финансовый директор / Казначей / Собственник», по умолчанию `default_role` компании.
- Кнопка «Войти» (красная) → `POST /api/session` → `/`.
- Свёрнутый блок «Я из жюри»: поиск по целевым компаниям и поле кода. Показывается, если `meta.demo_mode=false`. В демо-режиме поиск доступен сразу.

### 6.2 Главная «Альфа-Бизнес» (`/`) — критерий 9

- Верхняя панель: название компании, переключатель роли, ссылки «Лента», «Проверить новость», «Что мы о вас знаем», «Качество».
- **TodayWidget** первым блоком, заметно: «Сегодня важно для вас: 3 события» (`GET /api/brief`). Три строки: точка направления, вывод, «почему вам». Кнопка «Прочитать за 60 секунд» раскрывает действие для текущей роли. Ссылка «Вся лента».
- Ниже макет банка с плашкой «демо-данные»: **AccountsWidget** — 2–3 счёта, остатки детерминированно выводятся из выручки; **PaymentsWidget** — 5 последних «платежей» крупнейшим контрагентам (`GET /api/me/counterparties`).
- Данные: `useBrief()`, `useCounterparties('suppliers', 5)`, `useSession()`.

### 6.3 Лента (`/feed`)

- Заголовок «Лента для {компания}», переключатель роли, фильтры `FilterTag`: «Все», «Риски», «Возможности», «Влияние от среднего».
- Список `InsightCard` (`useInfiniteQuery` → `GET /api/feed`), «Показать ещё».
- **InsightCard** по статусам:
  - `ready`: строка меток (направление, влияние, «2 ч назад», «3 источника»), вывод, «почему вам», `ChainPreview` (одна строка со стрелками, обрезка многоточием, полный текст в подсказке), подвал (уверенность). Клик → `/insights/:id`.
  - `pending`: заголовок события, превью цепочки, кнопка «Разобрать для меня» → `POST /api/events/{id}/insight` → внутри карточки компактная лента шагов (`useRunEvents`) → после `end` карточка обновляется.
  - `generating`: «Готовим разбор…» и подписка на SSE по `run_id`.
  - `failed`: «Не удалось подготовить разбор» и кнопка «Повторить».
  - `stale` или `needs_review`: маленькая плашка.
- Пустая лента: «Пока нет событий, влияющих на вашу компанию» и кнопка «Проверить новость».
- Телеметрия: `feed_view` при открытии.

### 6.4 Карточка инсайта (`/insights/:insightId`)

Порядок блоков — 6 вопросов кейса (`08-agent.md` §8.3). Подписи — из `labels.ts`.

1. **Шапка:** «← Лента»; метки направления, влияния, уверенности; **вывод** крупно; «почему вам» вторым уровнем; строка события (заголовок, издания, время); кнопки «Как мы пришли к выводу» (открывает трассу в `SidePanel`) и «Спросить аналитика» (открывает `ChatPanel`).
2. **StatusNotice:** `stale` — «Профиль компании изменился. Пересчитать?» (`POST /api/events/{id}/insight`). `needs_review` — «Часть выводов не подтверждена источниками и требует проверки аналитиком». `verification.removed_claims > 0` — «Часть выводов скрыта: не удалось подтвердить источниками». `event.injection_suspected` — «В исходном тексте была попытка управлять ИИ — она проигнорирована».
3. **Что произошло:** факты (`ClaimText`), ниже приглушённо «Оговорки» (assumptions).
4. **Почему это важно вам:** `why_it_matters.summary`; `FeatureChips` — подписи признаков из профиля по `client_features_used` (клик ведёт в `/profile#feature`); **ChainGraph**.
5. **Риски** и **Возможности:** `ConsequenceList` — заголовок, утверждение, чипы «вероятность», «горизонт», «сила». Пустой список — «Существенных рисков не видим».
6. **Что можно сделать:** `ActionList`. Сначала действия для роли сессии с пометкой «для вас», затем остальные. Чипы «для казначея», «на этой неделе». `ProductChip` «Альфа-Банк: Валютный форвард» → `LeadModal` с текстом продукта, дисклеймером каталога, полем комментария и кнопкой «Оставить заявку (демо)». Подтверждение обязательно, затем `POST /api/leads`.
7. **Позиция Альфа-Банка:** `BankViewBlock` — утверждения `bank` с названием документа, датой и страницей; бейдж согласованности: «Согласуется с выводом», «Нейтрально», «Расходится с выводом». Если данных нет — «У аналитиков Альфа-Банка нет публикаций по теме».
8. **Источники:** нумерованный список с иконкой вида, названием, изданием, датой и внешней ссылкой.
9. **FeedbackBar:** «Полезно?» 👍/👎 → чипы причин → необязательный комментарий → `POST …/feedback`.

**ClaimText:** текст предложения и бейдж метки в конце. Клик по предложению открывает `SourceDrawer` со списком источников из `refs` (`GET /api/sources/{id}`): выдержка, полный текст по кнопке, ссылка на оригинал. Для `client_data` — таблица долей и контрагентов, для `cbr` — мини-график ряда. Телеметрия: `source_open`.

**ChainGraph:** `ReactFlow` с узлами и рёбрами из `insight.chain`. Позиции приходят с сервера. Масштаб, перетаскивание и соединение узлов отключены, `fitView`, высота 320 px (на мобильных 420 px, вертикальная раскладка: x и y меняются местами). Узлы — свои компоненты: событие (серый), отрасль или фактор, экспозиция компании (жирное число), последствие (цвет направления). Клик по узлу открывает его `source_ids` в `SourceDrawer`. Толщина ребра `1 + 4·weight`, подпись — вклад.

### 6.5 Трасса «Как мы пришли к выводу» (`SidePanel` и `/insights/:id/trace`)

- `RunSummary`: общее время, стоимость в ₽, использованные модели, число источников, результат проверки («Подтверждено 9 из 10 утверждений»).
- `AgentTimeline`: шаги по фазам — Приём новости → План → Сбор данных → Черновик → Проверка → Доработка → Готово. У каждого шага иконка фазы, заголовок из `title`, длительность и статус (warn — жёлтая точка, error — красная). Раскрытие показывает `payload`: аргументы инструмента, список E-id, для `llm.call` — модель, токены, стоимость, «из кеша». Для `verify.report` — полоса доли подтверждённых и список замечаний.
- Один и тот же компонент работает со статической трассой (`GET …/trace`) и с живой (`useRunEvents`). Новые шаги появляются каскадом, область объявлена `aria-live="polite"`.

### 6.6 Проверить новость (`/analyze`) — фича B

- Заголовок «Проверить любую новость». Подзаголовок «Вставьте ссылку или текст — покажем, как это влияет на {компания}».
- `Tabs`: «Ссылка» (`Input` URL) / «Текст» (`Textarea`, счётчик, минимум 200 символов, необязательный заголовок).
- Чипы-примеры (3 статичные ссылки из `labels.ts: ANALYZE_EXAMPLES`) для быстрого демо.
- Кнопка «Разобрать» (красная, единственный акцент экрана) → `POST /api/analyze` → `run_id`.
- Во время прогона: секундомер «12 с», живой `AgentTimeline`, кнопка заблокирована.
- `end: succeeded` → `GET /api/insights/{id}` → компактный инсайт: шапка, цепочка, свёрнутые секции, кнопка «Открыть полностью».
- `end: failed` → `ErrorState` с текстом по `error_code` (`08-agent.md` §17). Для `fetch_failed` и `unsupported_content` — кнопка «Вставить текст» переключает вкладку.
- Ниже «Мои проверки» (`GET /api/analyze/history`).

### 6.7 Чат «Спросить аналитика» (`ChatPanel` в `SidePanel` на карточке)

- Стартовые подсказки: «Что если ставка снизится до 12%?», «Покажи контрагентов в этой отрасли», «Где первоисточник?».
- Отправка → `POST …/chat` → `useRunEvents(run_id)`: компактные шаги инструментов («Смотрю ключевых контрагентов»). После `end` перезапрашивается история треда.
- Ответ ассистента — блоки `ClaimText` (метки и источники), ниже `FollowupChips`.
- Ошибки — сообщение в ленте чата с кнопкой «Повторить».

### 6.8 Что мы о вас знаем (`/profile`) — критерий 10 и обратная связь

- `FactsGrid`: отрасль (с ОКВЭД), регион, выручка, продукты в Альфа-Банке, страны ВЭД. У каждого факта пометка «из данных банка» или «уточнено вами».
- `IndustryMixBar` для закупок и продаж: горизонтальная сложенная полоса, топ-6 отраслей + «прочее» + «неизвестно». Подпись покрытия: «Данные по 90% платежей». При `basis=prior` — «Оценка по отраслевой модели».
- `CounterpartyTable`: топ-10 с переключателем поставщики/покупатели.
- `FactorList`: фактор, шкала экспозиции, «риск при росте» или «выгода при росте», причины.
- `OverridesForm`: основная отрасль (`Select` по справочнику из `GET /api/reference`), страны ВЭД и направление, наличие продуктов, свободная заметка → `PUT /api/me/profile/overrides`. Тост «Профиль обновлён, лента пересчитана», инвалидация `profile`, `feed`, `brief`.
- У признаков якоря `id="feature-<key>"` для переходов из карточки.

### 6.9 Качество (`/quality`)

Данные — `GET /api/quality` (`12-quality.md` §6).
- **Офлайн-метрики:** `MetricTile` для nDCG@5, P@5, обоснованности, полноты и доли противоречий; дата отчёта и размер набора.
- **Онлайн-метрики:** полезность (% 👍), доля открытий источников, доля уточняющих вопросов, время до инсайта (p50 и p95), стоимость одного инсайта.
- **Бюджет:** сегодня потрачено и лимит (полоса, режим), график за 7 дней по задачам (`BudgetChart`, recharts), таблица моделей (вызовы, токены, ₽, доля из кеша).
- **Проверка:** распределение `supported_share`, доля `needs_review`.
- **Очередь проверки:** список `needs_review` — только при `jury=true` или с админ-токеном.

## 7. Работа с API

### 7.1 Клиент (`api/client.ts`)

```ts
import createClient from 'openapi-fetch';
import type { paths } from './schema';

export const api = createClient<paths>({ baseUrl: '', credentials: 'include' });

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: unknown) { super(message); }
}
// unwrap({ data, error, response }): 401 → location.assign('/login'); error → throw new ApiError(...)
```

### 7.2 Хуки (`api/hooks.ts`)

| Хук | Ключ | Эндпоинт |
|---|---|---|
| `useMeta` | `['meta']` | `GET /api/meta` (staleTime 60 с) |
| `useSession` | `['session']` | `GET /api/session` |
| `useFeed(filters)` | `['feed', role, filters]` | `GET /api/feed` (infinite) |
| `useBrief` | `['brief', role]` | `GET /api/brief` |
| `useInsight(id)` | `['insight', id]` | `GET /api/insights/{id}` |
| `useTrace(id)` | `['trace', id]` | `GET /api/insights/{id}/trace` |
| `useProfile` | `['profile']` | `GET /api/me/profile` |
| `useCounterparties(dir, industry?)` | `['counterparties', dir, industry]` | `GET /api/me/counterparties` |
| `useReference` | `['reference']` | `GET /api/reference` (staleTime ∞) |
| `useSource(id)` | `['source', id]` | `GET /api/sources/{id}` |
| `useChat(insightId, threadId)` | `['chat', insightId, threadId]` | `GET /api/insights/{id}/chat` |
| `useAnalyzeHistory` | `['analyzeHistory']` | `GET /api/analyze/history` |
| `useMacro` | `['macro']` | `GET /api/macro` |
| `useQuality` | `['quality']` | `GET /api/quality` |

Мутации: `useLogin`, `useChangeRole` (инвалидирует `session`, `feed`, `brief`), `useGenerateInsight`, `useAnalyze`, `useSendChat`, `useFeedback`, `useSaveOverrides` (инвалидирует `profile`, `feed`, `brief`), `useCreateLead`. `sendUiEvent` — без ожидания ответа.

Глобально: `retry: 1` для запросов (кроме 4xx), `refetchOnWindowFocus: false`. Ленту обновляет фоновый `refetchInterval` 60 с.

### 7.3 SSE (`api/sse.ts`)

```ts
export type RunStatus = 'idle' | 'connecting' | 'running' | 'succeeded' | 'failed';
export interface RunEnd { status: 'succeeded' | 'failed' | 'cancelled'; insight_id: string | null;
  message_id: number | null; error_code: string | null; error_message: string | null;
  duration_ms: number | null; cost_rub: number }

export function useRunEvents(runId: string | null): {
  events: TraceEventOut[];    // уникальны по seq, отсортированы
  status: RunStatus;
  end?: RunEnd;
}
```

Реализация: `new EventSource(`/api/runs/${runId}/events`)`; `addEventListener('trace', …)` добавляет событие с дедупликацией по `seq`; `addEventListener('end', …)` сохраняет `end` и закрывает соединение. `onerror` без полученного `end` оставляет статус `connecting` (браузер переподключается сам). Если `end` не пришёл за 90 с — `failed` («Соединение потеряно»). При размонтировании соединение закрывается. Тип `TraceEventOut` берётся из `schema.d.ts`.

## 8. Тексты (`lib/labels.ts`)

`Record<…, string>` для каждого enum, чтобы TypeScript ловил пропуски: направления, уровни влияния и уверенности, типы утверждений, роли (полное и короткое имя), срочность, горизонты, вероятность, заголовки 6 секций, тексты ошибок по `error_code`, типы событий, подписи фаз трассы, причины обратной связи, `ANALYZE_EXAMPLES`. Названия отраслей, факторов и стран приходят из `GET /api/reference`, на клиенте не дублируются.

`lib/format.ts`: `formatShare(0.34) → "34%"`, `formatRub(1.2e9) → "1,2 млрд ₽"`, `formatRelative(date) → "2 ч назад"`, `formatDate(date) → "22 окт, 09:10"`. Используются `Intl` (`ru-RU`) и часовой пояс `Europe/Moscow`.

## 9. Адаптивность, доступность, производительность

- Мобильная вёрстка первична. Ширина чтения — 760 px. На главной от 1024 px две колонки. `SidePanel` на мобильных занимает весь экран.
- Семантические заголовки секций (h1–h3), видимый фокус, карточки открываются с клавиатуры (`Enter`), `aria-live` у живой трассы, контраст текста не ниже 4.5:1.
- Скелетоны вместо спиннеров для ленты и карточки. Ленивые чанки страниц. Без лишних перерисовок графа: узлы мемоизированы.

## 10. Тесты и скрипты

- **vitest:** `format.ts`, полнота `labels.ts`, `useRunEvents` с фейковым `EventSource` (дедупликация, `end`, таймаут), `ClaimText` (бейдж, открытие drawer), `InsightCard` (все статусы), `ChainGraph` (рендер узлов из фикстуры).
- **Фикстуры** — JSON-ответы API, записанные из бэкенда в режиме `LLM_MODE=fake` (`frontend/src/test/fixtures/*.json`).
- **(P2) Playwright smoke** на `docker compose` с `LLM_MODE=fake`: вход → лента → карточка → трасса → анализ текста → `end`.

`package.json`:

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "typecheck": "tsc --noEmit -p tsconfig.json",
    "test": "vitest run",
    "gen:api": "openapi-typescript openapi.json -o src/api/schema.d.ts",
    "format": "prettier --write src"
  }
}
```

`vite.config.ts`: плагин react; `server.proxy = { '/api': { target: 'http://localhost:8000', changeOrigin: false } }` (SSE через прокси Vite работает); `build.outDir = 'dist'`; `test.environment = 'jsdom'`.
