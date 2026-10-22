# 07. Ранжирование и «цепная реакция»

## 1. Задача

Для пары «компания × событие × роль» нужно получить:

1. **пути влияния** — как событие доходит до компании и с каким вкладом (это и есть «цепная реакция»);
2. **релевантность** — насколько сильно событие касается компании;
3. **итоговый скор** с учётом важности, свежести, доверия, региона и роли;
4. **направление** (риск, возможность, смешанное) и **уровень влияния**;
5. **превью цепочки** одной строкой для ленты. LLM для него не нужен.

Расчёт детерминированный и объяснимый. Каждое число в карточке можно проследить до данных. Модули: `ranking/effects.py` (матрица), `ranking/chain.py` (пути), `ranking/scorer.py` (скор), `ranking/service.py` (пакетный расчёт и запись), `ranking/rerank.py` (P2).

## 2. Входные модели

```python
# ranking/models.py
Channel = Literal["own", "supply", "demand", "factor"]
Direction = Literal["risk", "opportunity", "mixed"]
ImpactLevel = Literal["low", "medium", "high", "critical"]
Role = Literal["cfo", "treasurer", "owner"]

class IndustrySignal(BaseModel):
    industry_id: str; effect: Effect; impact: float; confidence: float     # 0.33 / 0.67 / 1.0

class FactorSignal(BaseModel):
    factor_id: str; direction: Literal[-1, 1]; impact: float; confidence: float

class EventSignal(BaseModel):
    event_id: int; title: str; event_type: str; importance: int; horizon: str
    first_seen_at: datetime; last_seen_at: datetime
    publisher_count: int; max_trust: float; tag_confidence: float
    geo: list[str]; industries: list[IndustrySignal]; factors: list[FactorSignal]
    visibility: Literal["public", "private"]; owner_company_id: str | None
    injection_suspected: bool
```

`EventSignal` собирается из `events`, `event_industries` и `event_factors` функцией `store.events.load_signals(event_ids)`. Профиль — `CompanyProfile` (`03-data.md` §7).

## 3. Матрица эффектов (`data/reference/effects.yaml: matrix`)

Для каждого канала и эффекта: направление для компании, сила (0..1) и механизм (текст для превью и подсказки LLM).

| Эффект на отрасль | `own` — своя отрасль | `supply` — отрасль-поставщик | `demand` — отрасль-покупатель |
|---|---|---|---|
| `prices_up` | возможность · 1.0 · рост цен реализации | риск · 1.0 · рост закупочных цен → себестоимость | возможность · 0.5 · у покупателей растёт выручка → платёжеспособность |
| `prices_down` | риск · 1.0 · давление на цены и маржу | возможность · 1.0 · закупки дешевеют → маржа | риск · 0.5 · у покупателей падают цены → давление на ваши цены и сроки оплаты |
| `demand_up` | возможность · 1.0 · рост спроса на вашу продукцию | риск · 0.4 · конкуренция за поставки → рост цен и сроков | возможность · 1.0 · покупатели нарастят закупки |
| `demand_down` | риск · 1.0 · снижение спроса | возможность · 0.4 · поставщики сговорчивее: скидки, отсрочки | риск · 1.0 · покупатели сократят закупки, вырастет дебиторка |
| `supply_down` | смешанное · 0.6 · дефицит на рынке: выше цены, но риск недопоставок | риск · 1.0 · перебои и дефицит поставок | риск · 0.6 · покупатели сокращают выпуск → меньше заказов |
| `supply_up` | риск · 0.6 · больше конкуренции → давление на цены | возможность · 0.6 · больше предложения → лучше условия закупок | возможность · 0.4 · покупатели наращивают выпуск → больше заказов |
| `costs_up` | риск · 1.0 · рост издержек отрасли | риск · 0.6 · поставщики переложат издержки в цены | риск · 0.5 · у покупателей растут издержки → давление на ваши цены и отсрочки |
| `costs_down` | возможность · 1.0 · снижение издержек отрасли | возможность · 0.6 · пространство для снижения закупочных цен | возможность · 0.4 · у покупателей освобождаются средства |
| `regulation_tighter` | риск · 1.0 · новые ограничения и затраты на соответствие | риск · 0.6 · риск сбоев у поставщиков | риск · 0.5 · ограничения у покупателей → меньше заказов |
| `support_measures` | возможность · 1.0 · доступ к мерам господдержки | возможность · 0.3 · поставщики стабильнее | возможность · 0.6 · господдержка покупателей → больше заказов |

Канал `factor`: сила 1.0. Направление: `d·σ > 0` → возможность (`opportunity_text` фактора), иначе риск (`risk_text`). Здесь `d` — направление фактора в событии, `σ` — знак экспозиции компании (`03-data.md` §5.2).

## 4. Пути влияния (`ranking/chain.py`)

Обозначения: `s = impact × confidence` — сила тега события; `W[ch]` — вес канала; `R[role][ch]` — множитель роли по каналу; `R_f[role][f]` — множитель роли по фактору (по умолчанию 1); `M[ch][eff]` — строка матрицы §3.

**Own** — для основной отрасли компании `m` (вес `w=1.0`) и дополнительных (`w=0.5`), если у события есть тег этой отрасли:

```
c = W[own] · R[role][own] · w · s · M[own][eff].strength
```

**Supply** — для каждого отраслевого тега `(i, eff)` с `Ŝ(i) ≥ min_share`:

```
c = W[supply] · R[role][supply] · Ŝ(i) · s · M[supply][eff].strength
```

**Demand** — то же с `B̂(i)` и `M[demand]`.

**Factor** — для каждого факторного тега `(f, d)`, если экспозиция компании `X(f) ≥ min_factor_exposure`:

```
c = W[factor] · R[role][factor] · R_f[role][f] · X(f) · s
```

Каждый вклад ограничен `max_path_contribution` (0.95). Пути с `c < 0.01` отбрасываются. Остальные сортируются по убыванию и нумеруются `P1, P2, …`.

```python
class CounterpartyBrief(BaseModel):
    name: str; share: float

class ChainPath(BaseModel):
    id: str                                   # P1.. по убыванию contribution
    channel: Channel
    industry_id: str | None = None
    industry_name: str | None = None
    effect: Effect | None = None
    factor_id: str | None = None
    factor_name: str | None = None
    factor_direction: Literal[-1, 1] | None = None
    company_weight: float                     # own: w; supply/demand: Ŝ/B̂; factor: X(f)
    raw_share: float | None = None            # фактическая доля из платежей (для текста), если есть
    basis: Literal["main_industry", "secondary_industry", "payments", "blended", "prior", "profile_factor"]
    coverage: float | None = None
    event_strength: float                     # s
    matrix_strength: float
    role_weight: float
    contribution: float
    direction: Direction
    mechanism: str
    top_counterparties: list[CounterpartyBrief] = []   # supply/demand: до 3 крупнейших в этой отрасли
    reasons: list[str] = []                   # factor: reasons из профиля
    feature_keys: list[str]                   # «suppliers.metallurgy», «factor.key_rate», «industry.main» …

class Exposure(BaseModel):
    event_id: int; company_id: str; role: Role
    paths: list[ChainPath]
    relevance: float
    direction: Direction
    channel_totals: dict[Channel, float]

def compute_exposure(event: EventSignal, profile: CompanyProfile, role: Role,
                     cfg: RankingConfig, tax: Taxonomy, counterparties: CounterpartyReader | None) -> Exposure: ...
```

`top_counterparties` заполняется, только если передан `counterparties` (DuckDB `top_counterparties` по компании, направлению и отрасли). В пакетном ранжировании контрагенты не запрашиваются ради скорости. Их добавляет инструмент агента `compute_exposure`.

## 5. Смешивание с типовыми долями и покрытие

Фактические доли из платежей известны не для всего объёма: часть контрагентов имеет отрасль `unknown`. Чтобы не завышать и не занижать влияние:

```
S(i)  = share_known поставщиков отрасли i (доля среди платежей с известной отраслью)
κ_S   = coverage поставщиков (доля объёма с известной отраслью)
S0(i) = typical_suppliers основной отрасли (нормированные)
Ŝ(i)  = κ_S · S(i) + (1 − κ_S) · S0(i)
```

Для покупателей то же: `B`, `κ_B`, `B0`.

- `basis = payments`, если `κ ≥ 0.95`; `blended`, если `0 < κ < 0.95`; `prior`, если платёжных данных нет (`κ = 0`).
- Если у компании `direction_unknown = true`, все связи считаются поставщиками, а для покупателей `B̂ = B0` (`basis = prior`).
- В тексте для пользователя (превью, `raw_share`) показывается **фактическая** доля от всего объёма (`share_total`) и рядом покрытие. Например: «34% ваших закупок (данные по 90% платежей)». При `prior` пишется «типично для отрасли ≈ 15%».

## 6. Итоговый скор (`ranking/scorer.py`)

```
relevance          R  = 1 − Π (1 − c_k)                          # noisy-OR по путям
importance_factor  I  = importance.base + importance.slope · importance / 5      # 0.6 + 0.4 · imp/5
freshness          φ  = 0.5 ^ (age_h / half_life_h[role]),  age_h — от events.last_seen_at
freshness_factor   F  = freshness.floor + (1 − freshness.floor) · φ             # 0.5 + 0.5 · φ
trust_factor       T  = max_trust · (1 + publisher_bonus · min(publisher_count − 1, publisher_bonus_cap))
region_bonus       G  = region_bonus, если region_code компании ∈ event.geo, иначе 0
score                 = R · I · F · T · (1 + G)
```

Noisy-OR выбран так: несколько слабых путей вместе дают заметную релевантность, но сумма не уходит за 1.

### 6.1 `config/ranking.yaml`

```yaml
version: 1
window_days: 7
min_relevance_to_store: 0.05
channel_weights: {own: 1.0, supply: 0.9, demand: 0.8, factor: 0.7}
secondary_industry_weight: 0.5
min_share: 0.02
min_factor_exposure: 0.15
max_path_contribution: 0.95
direction_mixed_ratio: 0.25
importance: {base: 0.6, slope: 0.4}
freshness: {floor: 0.5}
trust: {publisher_bonus: 0.05, publisher_bonus_cap: 4}
region_bonus: 0.10
impact_levels:
  critical: {min_score: 0.55, min_importance: 4}
  high: {min_score: 0.35}
  medium: {min_score: 0.18}
feed: {min_score: 0.10, min_relevance: 0.08, page_size: 20}
roles:
  cfo:
    half_life_h: 48
    channels: {own: 1.0, supply: 1.2, demand: 1.0, factor: 1.0}
    factors: {tax_burden: 1.3, customs_tariffs: 1.2, energy_prices: 1.2, key_rate: 1.1}
  treasurer:
    half_life_h: 24
    channels: {own: 0.8, supply: 0.9, demand: 0.9, factor: 1.4}
    factors: {key_rate: 1.4, credit_conditions: 1.3, payment_discipline: 1.3, cross_border_payments: 1.5,
              fx_usd: 1.5, fx_eur: 1.5, fx_cny: 1.5, fx_try: 1.5, fx_aed: 1.5, fx_inr: 1.5, fx_kzt: 1.5}
  owner:
    half_life_h: 96
    channels: {own: 1.3, supply: 1.0, demand: 1.2, factor: 0.9}
    factors: {gov_spending: 1.3, sanctions: 1.2, consumer_demand: 1.2, mortgage_market: 1.2}
rerank: {enabled: false, top_n: 20, alpha: 0.4}
```

## 7. Роли

Роль меняет вес каналов и факторов и скорость устаревания. Инсайт от роли **не зависит**: он один на пару «компания × событие». От роли зависят:

- порядок ленты и брифинга (`rankings` хранится по каждой роли);
- какое действие брифинг показывает первым (`owner_role`, `08-agent.md` §14);
- акцент текста: роль передаётся в промпт при генерации и выбирается по роли сессии, запустившей прогон, или по `default_role` демо-компании в прекомпьюте. На содержание фактов роль не влияет.

## 8. Направление и уровень влияния

```
sgn(path) = +1 (opportunity), −1 (risk), 0 (mixed)
D = Σ c_k · sgn_k,   T = Σ c_k
direction = mixed, если T = 0 или |D| < direction_mixed_ratio · T; иначе risk при D < 0, opportunity при D > 0

impact_level = critical, если score ≥ 0.55 и importance ≥ 4
             = high,     если score ≥ 0.35
             = medium,   если score ≥ 0.18
             = low       иначе
```

Пороги калибруются на офлайн-разметке (`12-quality.md` §3): медиана скора событий с оценкой 3 должна быть ≥ 0.35, с оценкой 0 — < 0.10.

## 9. Сервис ранжирования (`ranking/service.py`)

```python
class RankResult(BaseModel):
    exposure: Exposure
    components: RankComponents              # relevance, I, φ, F, T, G, score
    score: float; direction: Direction; impact_level: ImpactLevel
    chain_preview: str | None

class RankComponents(BaseModel):
    relevance: float; importance_factor: float; freshness: float; freshness_factor: float
    trust_factor: float; region_bonus: float; score: float

class RankingService:
    def rank_one(self, event: EventSignal, profile: CompanyProfile, role: Role, now: datetime) -> RankResult: ...
    def rank_company(self, company_id: str, *, now: datetime | None = None) -> int: ...     # все события окна × 3 роли
    def rank_events(self, event_ids: list[int], *, now: datetime | None = None) -> int: ... # для всех целевых компаний
    def rank_all(self, *, now: datetime | None = None) -> int: ...
```

- **Окно:** публичные события с `last_seen_at ≥ now − window_days`. Приватные ранжируются только для `owner_company_id` и только в момент intake.
- **Хранение:** upsert в `rankings` строк с `relevance ≥ min_relevance_to_store`. Для пары, ставшей нерелевантной, строка удаляется. `components_json` = `RankComponents`, `chain_json` = `Exposure` без контрагентов, `profile_version` — текущая версия профиля.
- **Когда считается:** задача `rank` в worker (по новым и обновлённым событиям — `rank_events`; раз в сутки — `rank_all`, чтобы обновить свежесть); после правки профиля (`rank_company`); в intake фичи B (`rank_one` для приватного события).
- **Производительность:** 115 компаний × ~500 событий × 3 роли ≈ 170 тыс. расчётов, около 2 с на чистом Python. Профили и сигналы загружаются один раз на вызов, без запросов в цикле.
- События с `injection_suspected` ранжируются как обычно, но прекомпьют их пропускает, а в карточке показывается предупреждение.

### 9.1 Превью цепочки

Строится по первому пути: `«{событие} → {звено} → {риск|возможность}: {механизм}»`.

| Канал | Звено |
|---|---|
| `supply` | `{raw_share}% ваших закупок — {отрасль}` (при `prior`: «типично для отрасли ≈ X% закупок — {отрасль}») |
| `demand` | `{raw_share}% ваших продаж — {отрасль}` |
| `own` | `ваша отрасль — {отрасль}` |
| `factor` | `{фактор}: {reasons[0]}` |

Событие обрезается до 60 символов по границе слова. Пример: «Металлурги поднимают цены на арматуру → 34% ваших закупок — металлургия → риск: рост закупочных цен → себестоимость».

## 10. LLM-переранжирование (P2, `ranking/rerank.py`)

Включается `rerank.enabled`. Раз в сутки (и для новых событий) для 20 лучших событий компании в её `default_role` модель `rerank` возвращает оценку 0..3:

```python
class RerankItem(BaseModel):
    event_id: int; relevance: Literal[0, 1, 2, 3]; reason: str = Field(max_length=200)
class RerankOutput(BaseModel):
    items: list[RerankItem]
```

`score' = score · (1 − alpha + alpha · relevance / 3)`. При `alpha = 0.4` оценка 0 даёт ×0.6, оценка 3 — ×1.0. Результат пишется в `rankings.rerank_score`, `score` пересчитывается. Вызовы кешируются, приоритет `precompute`.

## 11. Граф цепочки для интерфейса

Граф строится в финализации инсайта (`08-agent.md` §10) из трёх первых путей. Раскладка простая колоночная и считается на сервере, библиотека раскладки на клиенте не нужна.

```python
class ChainNode(BaseModel):
    id: str
    kind: Literal["event", "industry", "factor", "exposure", "consequence"]
    label: str                     # «Металлургия: цены растут»
    sublabel: str | None = None    # «вклад 0.37»
    direction: Direction | None = None
    x: int; y: int                 # колонка × 280, строка × 110
    source_ids: list[str] = []     # клик по узлу открывает источник

class ChainEdge(BaseModel):
    id: str; source: str; target: str; label: str | None = None; weight: float

class ChainGraph(BaseModel):
    nodes: list[ChainNode]; edges: list[ChainEdge]
```

Колонки: 0 — событие; 1 — отрасль или фактор с эффектом; 2 — экспозиция компании («34% закупок», «кредит + лизинг»); 3 — последствие (механизм, цвет по направлению). Толщина ребра на клиенте: `1 + 4 · weight`.

## 12. Пример расчёта

Компания SYN-DEMO-02 «Волга-Строй» (строительство зданий), роль `cfo`. Поставщики: металлургия 34% от всего объёма, покрытие κ_S = 0.90, поэтому `share_known` = 0.34 / 0.90 = 0.378. В типовых долях строительства металлургии нет, `S0 = 0`.

Событие: «Металлурги поднимают цены на арматуру на 8% с ноября». Два издания, Интерфакс (`trust` 0.9), `importance` 4, возраст 6 часов, `geo = [RU]`. Теги:
- `metallurgy / prices_up`, impact 3, confidence 3 → `s = 1.0`;
- `construction_buildings / costs_up`, impact 1, confidence 2 → `s = 0.33 · 0.67 = 0.22`;
- фактор `inflation`, рост, impact 1, confidence 1 → `s = 0.11`.

| Путь | Расчёт | Вклад | Направление |
|---|---|---|---|
| P1 supply · металлургия | Ŝ = 0.9 · 0.378 + 0.1 · 0 = 0.34; c = 0.9 · 1.2 · 0.34 · 1.0 · 1.0 | **0.367** | риск |
| P2 own · строительство | c = 1.0 · 1.0 · 1.0 · 0.22 · 1.0 | **0.220** | риск |
| P3 factor · инфляция | X = 0.2, σ = −1; c = 0.7 · 1.0 · 1.0 · 0.2 · 0.11 | **0.015** | риск |

- `R = 1 − (1 − 0.367)(1 − 0.220)(1 − 0.015) = 0.514`
- `I = 0.6 + 0.4 · 4/5 = 0.92`; `φ = 0.5^(6/48) = 0.917`, `F = 0.958`; `T = 0.9 · (1 + 0.05 · 1) = 0.945`; `G = 0`
- `score = 0.514 · 0.92 · 0.958 · 0.945 = 0.428` → **high**, направление **risk**
- Превью: «Металлурги поднимают цены на арматуру → 34% ваших закупок — металлургия → риск: рост закупочных цен → себестоимость»

У металлотрейдера SYN-DEMO-01 то же событие даст сильный путь `supply` (риск закупочных цен). Если в событии есть тег `wholesale_metals / prices_up`, добавится путь `own` (возможность: рост цен реализации). Тогда направление может стать `mixed`, и это корректно: трейдер частично перекладывает рост цен на покупателей.

## 13. Обязательные тесты (golden)

`backend/tests/unit/ranking/`:

1. Пример §12 воспроизводится с точностью 1e-3 по `R`, `score` и каждому вкладу.
2. `key_rate` растёт, у компании кредит (σ = −1) → риск. Ставка снижается → возможность.
3. Экспортёр (SYN-DEMO-04, `fx_cny` с σ = +1): рост юаня → возможность. Импортёр: риск.
4. Покрытие 0 → `basis = prior`, используются только типовые доли. Покрытие 1 → только платежи.
5. Роль `treasurer` ставит валютное событие выше событий о ценах поставщиков для SYN-DEMO-04, роль `cfo` — наоборот.
6. Региональный бонус применяется только при совпадении `RU-XXX`.
7. Правило `mixed`: смесь риска 0.5 и возможности 0.45 → `mixed`; 0.5 и 0.1 → `risk`.
8. Превью цепочки для каждого канала совпадает с эталонной строкой.
