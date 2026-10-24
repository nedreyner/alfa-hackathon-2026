# 12. Метрики качества и оценка (критерий 8)

## 1. Что измеряем

| Уровень | Что | Где считается | Где видно |
|---|---|---|---|
| Офлайн: ранжирование | nDCG@5, P@5, Recall@5 (rel=3), Spearman, точность направления; сравнение с базовыми вариантами | `eval/ranking_eval.py` на размеченном наборе | `eval/reports/latest.json`, страница «Качество», README |
| Офлайн: генерация | Обоснованность (LLM-судья + ручная выборка), полнота 6 блоков, противоречия, персонализация, точность чисел, доля `needs_review`, задержка, стоимость | `eval/grounding_eval.py`, `eval/completeness.py` | то же |
| Онлайн | Полезность (👍/👎), переходы к источникам, уточняющие вопросы, время до инсайта, стоимость инсайта, бюджет | SQL по `feedback`, `ui_events`, `chat_messages`, `agent_runs`, `llm_calls` | `GET /api/quality` |
| Процесс | Очередь экспертной проверки, еженедельный пересчёт весов | `admin` API, `alfa eval tune` | Страница «Качество» |

## 2. Офлайн-набор

### 2.1 Состав

- **6 демо-компаний × 10 событий = 60 суждений** (ADR-20). События берутся из seed-набора.
- Кандидаты для компании формируются пулингом, чтобы не подыгрывать своему ранжированию: 6 лучших по нашему скору + 4 случайных из событий, у которых есть хотя бы один отраслевой или факторный тег (фиксированный seed генератора случайных чисел).
- **Шкала релевантности:**
  - 3 — сильно и прямо влияет на финансы или операции компании (своя отрасль, ключевые поставщики или покупатели, существенный фактор);
  - 2 — заметное влияние, руководителю стоит знать;
  - 1 — слабое или косвенное;
  - 0 — не влияет.
- **Направление:** `risk`, `opportunity`, `mixed` или `none` (при оценке 0).

### 2.2 Формат `eval/labels.csv`

```csv
company_id,seed_id,relevance,direction,labeler,notes
SYN-DEMO-02,s-20261021-0007,3,risk,human:anna,"арматура — ключевая закупка"
```

- `seed_id` — id ведущей новости события. Он стабилен между пересборками базы. При оценке событие находится по новости с этим `seed_id`.
- `labeler`: `human:<имя>` или `llm`. Если есть строки `human:*`, метрики считаются **только** по ним (при нескольких разметчиках пары берётся `human:final`, иначе первая). Пока ручной разметки нет, отчёт считается по строкам `llm` и явно помечает это: `dataset.labels_source = "llm"`, на странице «Качество» — «предразметка моделью, до ручной проверки».

### 2.3 Протокол разметки

1. `alfa eval prelabel --companies demo --max-cost 5` — пул кандидатов сохраняется в `eval/pool.csv` (стабилен между пересборками), затем LLM-предразметка промптом `eval_label` (оценка и направление, задача `eval_label`: Kimi K2.6 — модель другого семейства, чем Gemma, размечающая новости) для строк, которых ещё нет (`labeler=llm`). Один вызов на компанию, 24.10.2026 — 3,6 ₽ за 60 суждений.
2. `alfa eval label --company SYN-DEMO-02` — интерактивный CLI: показывает профиль компании (`profile_brief`), заголовок, summary и теги события. **Наш скор не показывается.** Если есть предразметка, она показывается как подсказка. Человек вводит оценку и направление, строка становится `human:<имя>`.
3. Двое размечают независимо 20 общих суждений. Согласие (взвешенная каппа Коэна) пишется в отчёт. Расхождения обсуждаются, финальная оценка фиксируется.

## 3. Метрики ранжирования (`alfa_insight/evaluation/ranking_eval.py`)

Для каждой компании на её размеченных событиях: скор считается в `default_role` при фиксированном `now = max(published_at seed) + 2ч` и упорядочивается по убыванию.

```
DCG@k   = Σ_{i=1..k} (2^{rel_i} − 1) / log2(i + 1)
nDCG@k  = DCG@k / IDCG@k                         (IDCG — DCG идеального порядка; IDCG=0 → компания пропускается)
P@5     = |{топ-5 с rel ≥ 2}| / 5
R3@5    = |{топ-5 с rel = 3}| / |{rel = 3}|
Spearman ρ между score и rel
DirAcc  = среди rel ≥ 2 и direction ≠ none: совпадение направления (mixed против risk или opportunity = 0.5)
```

Итог — среднее по компаниям и значения по каждой.

**Базовые варианты** для сравнения (главный аргумент для жюри):
- `random` — случайный порядок, среднее по 100 перестановкам;
- `industry_only` — только канал `own`: веса `supply`, `demand` и `factor` равны 0;
- `no_payments` — без платёжных данных: `κ = 0`, только типовые доли отрасли.

Целевой результат для README: «Цепная реакция поднимает nDCG@5 с X (industry_only) до Y». Показываем фактические числа, без подгонки.

**Калибровка порогов** (`07-ranking.md` §8): медиана скора событий с rel=3 должна быть ≥ 0.35, с rel=0 — < 0.10. Отчёт печатает медианы по каждой оценке.

## 4. Метрики генерации

**Набор:** для каждой демо-компании 3 события с rel ≥ 2 → 18 инсайтов. `alfa eval generate --top 3 --max-cost 20`: режим `pipeline`, живой LLM, результат в кеше. Повторные прогоны оценки бесплатны (`replay`).

| Метрика | Определение | Цель |
|---|---|---|
| `grounded_share_llm` | Доля `supported` (partial = 0.5) среди утверждений `fact` и `bank` по вердиктам судьи | ≥ 0.85 |
| `grounded_share_human` | То же по ручной проверке 20 случайных утверждений (`alfa eval grounding-check --sample 20` → `eval/grounding_check.csv`, колонка `human_verdict`) | ≥ 0.8 |
| `judge_agreement` | Согласие судьи и человека на этой выборке | показываем как есть |
| `completeness` | Доля инсайтов, где есть все 6 блоков (`bank_view` засчитывается и при `no_data` с корректным `available=false`) | 1.0 |
| `contradiction_rate` | Доля инсайтов с непустым `contradictions` у судьи | ≤ 0.1 |
| `personalization_rate` | Доля инсайтов, где `client_features_used` содержит хотя бы один ключ `suppliers.*`, `buyers.*`, `products.*`, `ved.*` или `factor.*` (не только `industry.main`) | ≥ 0.9 |
| `numbers_match_rate` | Доля утверждений `fact` и `bank` с числами, прошедших `numbers_match` | ≥ 0.95 |
| `needs_review_share` | Доля `needs_review` | ≤ 0.1 |
| `latency_ms` p50 и p95 | `finished_at − started_at` прогонов | p50 ≤ 12 с |
| `cost_rub_mean` | Средняя стоимость инсайта | показываем |

Плюс для фичи B: 10 «незнакомых» ссылок (собираются в день оценки, `eval/analyze_urls.txt`) → доля успешных прогонов и p50/p95 полного времени. Цель — p50 ≤ 20 с.

## 5. Отчёт (`eval/reports/latest.json`)

```json
{
  "generated_at": "2026-10-25T12:00:00Z",
  "dataset": {"companies": 6, "judgements": 60, "human_labeled": 60, "kappa": 0.71, "seed_hash": "…"},
  "ranking": {
    "ndcg@5": 0.0, "p@5": 0.0, "recall_rel3@5": 0.0, "spearman": 0.0, "direction_acc": 0.0,
    "per_company": {"SYN-DEMO-01": {"ndcg@5": 0.0, "p@5": 0.0}},
    "baselines": {"random": {"ndcg@5": 0.0}, "industry_only": {"ndcg@5": 0.0}, "no_payments": {"ndcg@5": 0.0}},
    "score_medians_by_rel": {"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0}
  },
  "generation": {
    "insights": 18, "grounded_share_llm": 0.0, "grounded_share_human": 0.0, "judge_agreement": 0.0,
    "completeness": 0.0, "contradiction_rate": 0.0, "personalization_rate": 0.0, "numbers_match_rate": 0.0,
    "needs_review_share": 0.0, "latency_ms": {"p50": 0, "p95": 0}, "cost_rub_mean": 0.0
  },
  "analyze": {"runs": 10, "success_rate": 0.0, "latency_ms": {"p50": 0, "p95": 0}},
  "config": {"ranking_version": 1, "prompt_versions": {}, "models": {}, "llm_mode": "replay"}
}
```

`alfa eval report` собирает JSON и `eval/reports/latest.md` (таблица для README). Отчёт коммитится: это артефакт сдачи. Код — пакет `alfa_insight/evaluation/` (`dataset`, `metrics`, `labeling`, `ranking_eval`, `generation_eval`, `report`, `tune`, `commands`); `/api/quality` отдаёт сводку отчёта `OfflineSummary` (`09-api.md`).

**Результат 24.10.2026** (предразметка LLM, 60 суждений, 18 инсайтов): nDCG@5 — 0,82 у цепной реакции против 0,50 «только своя отрасль» и 0,43 случайного порядка. Вариант «без платёжных данных» даёт те же 0,83: в пуле преобладают макрособытия (ставка, курс), где влияние идёт через фактор, а не через контрагентов; канал платежей меняет скор до 0,13, но не порядок внутри пула. Обоснованность по судье 0,98, противоречия 0,22 (судья находит расхождения трактовок решения по ставке), p50 инсайта 26 с. Фича B: 8 из 10 свежих ссылок разобраны, 2 — `fetch_failed` (ТАСС), p50 22,6 с.

## 6. Онлайн-метрики (`services/quality.py`)

Окно по умолчанию — 7 суток.

| Метрика | Расчёт |
|---|---|
| `useful_rate` | `SUM(useful) / COUNT(*)` из `feedback` |
| `negative_reasons` | Распределение `reason` при `useful = 0` |
| `source_ctr` | Различные `insight_id` с `source_open` / различные `insight_id` с `insight_open` (`ui_events`) |
| `trace_open_rate` | То же для `trace_open` |
| `followup_rate` | Различные `insight_id` с сообщением пользователя в `chat_messages` / открытые инсайты |
| `time_to_insight_ms` | p50 и p95 `finished_at − created_at` у `agent_runs` с `kind ∈ (insight, analyze)` и `status = succeeded` (перцентили в Python) |
| `cost_per_insight_rub` | `AVG(cost_rub)` тех же прогонов |
| `run_failure_rate` | Доля `failed` по видам прогонов, топ `error_code` |
| `budget` | Сегодня: потрачено, лимит, режим; по дням за 7 суток в разрезе задач; по моделям: вызовы, токены, ₽, доля из кеша (`llm_calls`) |
| `verification` | Среднее `supported_share` (из `insights.verification_json`), доля `needs_review`, среднее `removed_claims` |

```python
class QualityResponse(BaseModel):
    offline: dict[str, Any] | None           # содержимое latest.json или None
    online: OnlineMetrics
    budget: BudgetStats
    verification: VerificationStats
    review_queue_size: int
    window_days: int
```

## 7. Процесс

- **Очередь экспертной проверки:** инсайты `needs_review` и с `confidence_level=low` попадают в `GET /api/admin/review-queue`. Эксперт утверждает (`published`) или отклоняет (`rejected`, скрывается из ленты) с комментарием. Отклонённые попадают в набор для разбора ошибок промптов.
- **Еженедельный пересчёт весов** (`alfa eval tune`):
  1. Данные: размеченный набор плюс онлайн-обратная связь за неделю. `useful=1` считается как rel=2, `useful=0` с `reason=not_relevant` — как rel=0.
  2. Перебор по сетке весов каналов `{own, supply, demand, factor}` от 0.5 до 1.5 с шагом 0.1 при фиксированных множителях ролей. Максимизируется средний nDCG@5 со штрафом `λ·Σ(w − w0)²` (λ = 0.5) против переобучения.
  3. Вывод — предлагаемый diff `config/ranking.yaml` и сравнение метрик «было / стало». Человек применяет его вручную коммитом.
- **Разбор отрицательной обратной связи:** раз в неделю — топ причин 👎 и 5 примеров по каждой, затем решение по промптам и весам.

## 8. CLI

```
alfa eval prelabel [--companies demo] [--max-cost RUB]
alfa eval label --company ID [--labeler NAME]
alfa eval ranking [--baselines]
alfa eval generate --top 3 [--max-cost RUB]
alfa eval grounding-check --sample 20
alfa eval analyze-urls eval/analyze_urls.txt [--max-cost RUB]
alfa eval report
alfa eval tune [--step 0.25]
```

`eval tune` по умолчанию перебирает сетку с шагом 0,25 (625 комбинаций, секунды); шаг 0,1 из §7 — `--step 0.1`.
