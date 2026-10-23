# 03. Данные: контракт, справочники, хранилища

## 1. Источники данных

| Источник | Формат | Объём (из исходного анализа) | Где лежит | В git |
|---|---|---|---|---|
| Компании | CSV | ≈85 тыс. строк; 115 с выручкой ≥ 15 млрд ₽, из них 108 клиенты | `data/raw/` | нет |
| Продукты банка у компаний | CSV или колонки в «компаниях» | кредит у 43% целевых, лизинг у 62% | `data/raw/` | нет |
| ВЭД (страна по данным ФНС) | CSV или колонка в «компаниях» | заполнено у ≈50% | `data/raw/` | нет |
| Платежи между компаниями | CSV | ≈1,38 млн связей; у 113 из 115 целевых есть платежи | `data/raw/` | нет |
| Аналитика Альфа-Банка | 9 PDF | — | `data/raw/research/` | нет (A7) |
| Синтетический аналог CSV | CSV | ≈3 тыс. компаний, ≈60 тыс. связей | `data/synthetic/` | **да** |
| Новости | RSS, HTML | 200–1500 в сутки до префильтра | SQLite | seed-набор `data/seed/news.jsonl` — да |
| Макро ЦБ | SOAP/XML | ставка и 7 валют | SQLite | снимок `data/seed/macro.json` — да |

Профиль данных выбирается переменной `DATA_PROFILE=real|synthetic`. При `real` используется `config/data_mapping.yaml`, при `synthetic` — `config/data_mapping.synthetic.yaml`. Остальной код от профиля не зависит.

## 2. Логическая модель CSV (контракт)

Код работает только с **логическими** таблицами и полями ниже. Физические имена колонок задаются маппингом (§3).

### 2.1 `companies`

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `company_id` | str | да | Идентификатор в данных кейса (если его нет — ИНН) |
| `inn` | str | нет | ИНН (10 или 12 цифр) |
| `name` | str | да | Название |
| `okved` | str | да | Основной ОКВЭД-2, например `46.72.2` |
| `okved_secondary` | str[] | нет | Дополнительные ОКВЭД (через `,` или `;`) |
| `region_code` | str | нет | Код региона (ISO 3166-2:RU, например `RU-MOW`) или исходная строка |
| `region_name` | str | нет | Название региона |
| `revenue_rub` | float | да | Выручка в рублях (после трансформаций) |
| `employees` | int | нет | Численность |
| `is_client` | bool | да | Клиент банка |
| `group_id` | str | нет | Группа или холдинг |

### 2.2 `company_products` (длинный формат)

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `company_id` | str | да | |
| `product_code` | enum | да | `credit`, `leasing`, `deposit`, `guarantee`, `factoring`, `acquiring`, `salary`, `fx`, `other` |
| `amount_rub` | float | нет | Объём или лимит |

### 2.3 `company_ved`

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `company_id` | str | да | |
| `country_raw` | str | да | Строка страны как в источнике («КИТАЙ», «Китайская Народная Республика») |
| `country_iso2` | str | вычисляется | Через `countries.yaml` (§5.5) |
| `direction` | enum | нет | `import`, `export`, `unknown` |
| `amount_rub` | float | нет | |

### 2.4 `payments`

| Поле | Тип | Обяз. | Описание |
|---|---|---|---|
| `company_id` | str | да | Компания, с точки зрения которой описан платёж |
| `counterparty_id` | str | да | Идентификатор контрагента (в пространстве `company_id` или ИНН) |
| `counterparty_inn` | str | нет | |
| `counterparty_name` | str | нет | |
| `counterparty_okved` | str | нет | |
| `direction` | enum | да | `out` — компания платит контрагенту (**поставщик**), `in` — контрагент платит компании (**покупатель**) |
| `amount_rub` | float | нет | Сумма за период |
| `tx_count` | int | нет | Количество операций |
| `period` | str | нет | Период (месяц или год) |

## 3. Маппинг колонок (`config/data_mapping.yaml`)

### 3.1 Формат

```yaml
profile: real
target_revenue_rub: 15_000_000_000
tables:
  companies:
    path: data/raw/companies.csv
    csv: {delimiter: ";", encoding: auto, header: true, decimal: ","}
    columns:                       # логическое_поле: физическая_колонка | null
      company_id: client_id
      inn: inn
      name: short_name
      okved: okved_main
      okved_secondary: null
      region_code: null
      region_name: region
      revenue_rub: revenue
      employees: null
      is_client: is_client
      group_id: null
    transforms:
      revenue_rub: {multiply: 1000}                      # если выручка в тыс. ₽
      is_client: {true_values: ["1", "Да", "да", "Y", "true"]}
      region_code: {map_file: data/reference/regions.yaml}   # опционально
  products:
    mode: wide                     # long | wide
    source: companies              # для wide — из какой таблицы
    flags:                         # product_code: колонка-флаг
      credit: has_credit
      leasing: has_leasing
    amounts: {credit: credit_amount}          # опционально
    true_values: ["1", "Да", "Y", "true"]
  ved:
    mode: wide
    source: companies
    country_column: ved_country_fns
    direction_column: null
    split: [",", ";"]              # если в ячейке несколько стран
  payments:
    path: data/raw/payments.csv
    csv: {delimiter: ";", encoding: auto, header: true, decimal: ","}
    mode: company_counterparty     # company_counterparty | payer_payee
    columns:
      company_id: client_id
      counterparty_id: kontragent_id
      counterparty_inn: kontragent_inn
      counterparty_name: kontragent_name
      counterparty_okved: null
      direction: direction
      amount_rub: amount
      tx_count: cnt
      period: null
    direction_values: {out: ["D", "debit", "списание", "out"], in: ["C", "credit", "зачисление", "in"]}
    counterparty_key: company_id   # company_id | inn — как связать контрагента с таблицей companies
    exclude_self: true
    exclude_intragroup: true       # выкидывать платежи внутри group_id
weight_basis: auto                 # auto | amount | tx_count | links
```

Pydantic-модель конфига — `alfa_insight/data/mapping.py: DataMapping`. Все значения выше, кроме `path` и `columns`, имеют умолчания.

### 3.2 Трансформации

| Ключ | Действие |
|---|---|
| `multiply: k` | Умножить число |
| `true_values: [...]` | Строку привести к bool (сравнение после `strip().lower()`) |
| `map: {a: b}` | Заменить значения |
| `map_file: path` | Загрузить словарь замен из YAML |
| `okved_normalize: true` | Применяется к ОКВЭД всегда: убрать пробелы, `,` заменить на `.`, удалить хвостовые точки |
| `strip_quotes: true` | Убрать кавычки-«ёлочки» и `"` в названиях |

Числа читаются как строки и приводятся в SQL: `TRY_CAST(REPLACE(REPLACE(REPLACE(x, ' ', ''), ' ', ''), ',', '.') AS DOUBLE)` (обычный и неразрывный пробел).

### 3.3 Продукты и ВЭД

- `mode: long`: отдельный файл с колонками логической таблицы.
- `mode: wide`: флаги или страна в колонках таблицы `source`. Сборка разворачивает их в длинный формат.

### 3.4 Режимы платежей и запасные варианты

| Ситуация в реальном CSV | Режим | Как получить `direction` |
|---|---|---|
| Колонки «компания», «контрагент», «направление» | `company_counterparty` | Через `direction_values` |
| Колонки «плательщик», «получатель» | `payer_payee` | Строка разворачивается в две: для плательщика `out`, для получателя `in`, если он в `companies` |
| Направления нет совсем | `company_counterparty` + `direction: null` | Все связи считаются `out`, у профиля флаг `direction_unknown=true`. Канал `demand` строится только из типовых долей отрасли |
| Нет суммы | `weight_basis: auto` | Порядок: `amount` → `tx_count` → `links` (количество связей) |

`weight_basis: auto` выбирает первую базу, заполненную не менее чем в 80% строк. Выбор пишется в `build_meta`.

В режиме `payer_payee` логические колонки маппинга — `payer_id`, `payee_id`, `amount_rub`, `tx_count`, `period`. Названий, ИНН и ОКВЭД контрагента в этом режиме нет, поэтому каскад §6.1 опирается только на таблицу компаний.

Если в данных нет названий компаний (`columns.name: null`), имя строится как «Компания <company_id>».

### 3.5 Реальные данные кейса (проверено в T1.6)

| Файл | Что внутри | Маппинг |
|---|---|---|
| `df_Uid_data_hack.csv` (`;`, UTF-8) | 85 525 строк компаний: `SYNTHETIC_U`, ОКВЭД, выручка в рублях, `CL_TYPE` (`CLIENT`, `CLOSE_CLIENT`, `PROSPECT`), флаги продуктов `CL_PRODUCT_*_MARK` и `FACTORING_MARK` (`0.0`/`1.0`), `FTS_COUNTRY_NAME` (несколько стран через запятую), `GROUP_ID`, `REGION` | `companies` + `products: wide` + `ved: wide` |
| `df_Uid_payment_hack.csv` (`;`) | 1 380 585 строк `BENEFICIARY`, `PAYER`, `PAY_AMT`, `PAY_CNT` | `payments: payer_payee` |
| `df_Fid_Uid_link_hack.csv` | Связи физлиц с компаниями | В текущей версии не используется |

Особенности:
- Названий и ИНН нет. В интерфейсе компания показывается по отрасли и региону.
- Один `SYNTHETIC_U` (`U_428697`) встречается в 12 разных строках с разными ОКВЭД и выручкой. Такие неоднозначные id исключаются целиком, полные дубли строк схлопываются.
- Контрагенты вне таблицы компаний (≈63% контрагентов целевых) не имеют ни ОКВЭД, ни названия. Медиана покрытия по объёму — 0.27. Это свойство набора: ранжирование смешивает фактические доли с типовыми пропорционально покрытию (`07-ranking.md` §5).
- 54 812 платежей самому себе и ≈69 тыс. строк внутри групп исключаются.

Отчёт `alfa data validate` на реальных данных: 115 целевых, 108 клиентов (94%), кредит 42.6%, лизинг 61.7%, ВЭД 50.4%, 1 380 585 исходных платежей, у 113 из 115 целевых есть платежи.

## 4. Сборка DuckDB (`alfa data build`)

### 4.1 Шаги

1. Загрузить маппинг, проверить, что файлы существуют.
2. **Подготовить CSV.** Определить кодировку: `encoding: auto` пробует `utf-8-sig`, затем `cp1251`. Если не UTF-8 — перекодировать потоком во временный файл `data/runtime/tmp/<name>.utf8.csv`. Встроенный CSV-ридер DuckDB понимает только utf-8, utf-16 и latin-1.
3. Прочитать в staging-таблицы: `read_csv(path, delim=?, header=true, all_varchar=true, quote='"', escape='"', ignore_errors=false)`. Битые строки — ошибка с номером строки.
4. Нормализовать в логические таблицы (§4.2) с трансформациями.
5. Вычислить `okved_industry` (§6.1) в Python для всех различных кодов ОКВЭД из `companies` и `payments`.
6. Вычислить `target_companies` (выручка ≥ `target_revenue_rub`) — с ними работают все производные таблицы.
7. Построить производные таблицы (§6) SQL-скриптами из `data/build_sql.py`.
8. Посчитать факторы (§6.4) и профили (§7) в Python и записать в `company_factors` и `profiles`.
9. Записать `build_meta` (профиль данных, время, хеши исходников, `weight_basis`, версия таксономии) и `data_quality` (§10).
10. Собрать во временный файл `analytics.duckdb.tmp`, затем `os.replace` в `analytics.duckdb`.

Сборку пропускаем, если в существующей базе `build_meta.sources_hash` совпадает с хешем исходников и версий справочников (`--force` пересобирает).

### 4.2 DDL нормализованных таблиц

```sql
CREATE TABLE companies (
  company_id VARCHAR PRIMARY KEY, inn VARCHAR, name VARCHAR NOT NULL,
  okved VARCHAR, okved_secondary VARCHAR[], region_code VARCHAR, region_name VARCHAR,
  revenue_rub DOUBLE, employees INTEGER, is_client BOOLEAN NOT NULL, group_id VARCHAR
);
CREATE TABLE company_products (
  company_id VARCHAR NOT NULL, product_code VARCHAR NOT NULL, amount_rub DOUBLE
);
CREATE TABLE company_ved (
  company_id VARCHAR NOT NULL, country_raw VARCHAR NOT NULL, country_iso2 VARCHAR,
  direction VARCHAR NOT NULL DEFAULT 'unknown', amount_rub DOUBLE
);
CREATE TABLE payments (
  company_id VARCHAR NOT NULL, counterparty_id VARCHAR NOT NULL, counterparty_inn VARCHAR,
  counterparty_name VARCHAR, counterparty_okved VARCHAR, direction VARCHAR NOT NULL,
  amount_rub DOUBLE, tx_count INTEGER, period VARCHAR
);
CREATE TABLE okved_industry (okved VARCHAR PRIMARY KEY, industry_id VARCHAR NOT NULL);
CREATE TABLE target_companies (company_id VARCHAR PRIMARY KEY);
CREATE TABLE build_meta (key VARCHAR PRIMARY KEY, value VARCHAR);
```

## 5. Справочники (`data/reference/`)

Все справочники — YAML с Pydantic-валидацией (`reference/models.py`). У каждого файла есть поле `version`, оно входит в хеш сборки и в ключ LLM-кеша для промпта разметки.

### 5.1 Отрасли (`industries.yaml`)

Формат записи:

```yaml
version: 1
industries:
  - id: wholesale_metals
    name: Оптовая торговля металлами
    okved_prefixes: ["46.72"]
    factor_sensitivity:            # factor_id: [вес 0..1, знак -1|1]
      customs_tariffs: [0.5, -1]
      key_rate: [0.5, -1]
      fx_cny: [0.4, -1]
      gov_spending: [0.3, 1]
      mortgage_market: [0.3, 1]
    typical_suppliers: {metallurgy: 0.8, metal_products: 0.1, transport_logistics: 0.1}
    typical_buyers: {construction_buildings: 0.35, metal_products: 0.2, machinery: 0.2, construction_infrastructure: 0.15, construction_specialized: 0.1}
    keywords: [металлопрокат, арматура, сталь, металлобаза, лист, труба]
```

Сопоставление ОКВЭД → отрасль: **самый длинный совпавший префикс** среди всех `okved_prefixes`. Перед сравнением код нормализуется (§3.2). Префиксы не короче 2 знаков. Не нашли — `unknown`. Веса поставщиков и покупателей нормируются кодом до суммы 1.

Полный список (обозначение `key_rate −0.4` означает вес 0.4 и знак −1):

| id | Название | ОКВЭД | Чувствительность к факторам | Типовые поставщики | Типовые покупатели | Ключевые слова |
|---|---|---|---|---|---|---|
| `agriculture` | Сельское хозяйство, лес, рыболовство | 01, 02, 03 | energy_prices −0.3, logistics −0.4, fx_usd +0.3, labor_costs −0.3 | chemicals .3, wholesale_fuel .2, wholesale_tech_equipment .2, machinery .15, wholesale_chemicals .15 | food_production .5, wholesale_agri_food .4, retail .1 | зерно, пшеница, урожай, агрохолдинг, удобрение, скот, рыба |
| `food_production` | Пищевая промышленность и напитки | 10, 11, 12 | consumer_demand +0.6, energy_prices −0.3, inflation −0.3 | agriculture .5, wholesale_agri_food .2, plastics_rubber .1, wood_paper .1, transport_logistics .1 | retail .5, wholesale_agri_food .35, hospitality .15 | молоко, мясо, сахар, хлеб, напиток, кондитерский, пищевой |
| `oil_gas` | Добыча нефти и газа | 06, 09.1 | oil_prices +0.9, sanctions −0.6, fx_usd +0.6, tax_burden −0.5 | machinery .3, construction_infrastructure .2, business_services .2, metal_products .15, transport_logistics .15 | oil_refining .6, power_utilities .2, wholesale_fuel .2 | нефть, газ, добыча, скважина, месторождение, ОПЕК |
| `coal` | Добыча угля | 05 | fx_usd +0.5, logistics −0.6, sanctions −0.5 | machinery .4, transport_logistics .3, wholesale_fuel .3 | power_utilities .5, metallurgy .4, wholesale_other .1 | уголь, угольный, разрез, шахта |
| `mining_metal_ores` | Добыча руд и прочих полезных ископаемых | 07, 08, 09.9 | fx_usd +0.4, energy_prices −0.3 | machinery .4, wholesale_fuel .2, chemicals .2, transport_logistics .2 | metallurgy .7, building_materials .3 | руда, рудник, ГОК, щебень, золото, песок |
| `oil_refining` | Нефтепереработка | 19 | oil_prices −0.6, tax_burden −0.5 | oil_gas .8, chemicals .1, machinery .1 | wholesale_fuel .6, transport_logistics .2, chemicals .2 | бензин, дизель, НПЗ, нефтепродукт, демпфер |
| `power_utilities` | Электроэнергетика, газо- и теплоснабжение | 35 | energy_prices +0.6, key_rate −0.3 | oil_gas .3, coal .2, machinery .2, electrical_equipment .2, construction_infrastructure .1 | metallurgy .25, real_estate .25, public_social .2, chemicals .15, retail .15 | электроэнергия, тариф, ТЭЦ, энергосбыт, теплоснабжение |
| `water_waste` | Водоснабжение, отходы | 36, 37, 38, 39 | tax_burden −0.3 | machinery .4, power_utilities .3, chemicals .3 | real_estate .4, public_social .3, metallurgy .3 | водоканал, отходы, ТКО, утилизация |
| `textile_apparel` | Текстиль, одежда, кожа | 13, 14, 15 | fx_cny −0.5, consumer_demand +0.5 | wholesale_other .4, chemicals .3, agriculture .3 | retail .6, wholesale_consumer_goods .4 | ткань, одежда, текстиль, обувь, швейный |
| `wood_paper` | Дерево, бумага, полиграфия | 16, 17, 18 | fx_usd +0.4, logistics −0.5, sanctions −0.4 | agriculture .4, chemicals .3, power_utilities .3 | construction_buildings .3, wholesale_construction_materials .3, food_production .2, retail .2 | древесина, пиломатериал, фанера, бумага, целлюлоза, картон |
| `chemicals` | Химия, удобрения, нефтехимия | 20 | energy_prices −0.6, fx_usd +0.4, sanctions −0.4, logistics −0.4 | oil_gas .4, oil_refining .3, power_utilities .2, mining_metal_ores .1 | agriculture .3, plastics_rubber .3, wholesale_chemicals .2, construction_specialized .2 | удобрение, аммиак, карбамид, полимер, нефтехимия |
| `pharma` | Фармацевтика | 21 | fx_inr −0.4, fx_cny −0.4, fx_eur −0.3 | chemicals .4, wholesale_chemicals .3, plastics_rubber .3 | wholesale_consumer_goods .6, public_social .4 | лекарство, препарат, фармацевтический, субстанция, маркировка |
| `plastics_rubber` | Резина и пластмассы | 22 | oil_prices −0.4, fx_cny −0.3 | chemicals .7, oil_refining .3 | food_production .3, construction_specialized .3, automotive_manufacturing .2, retail .2 | пластик, упаковка, шина, резина, ПЭТ |
| `building_materials` | Стройматериалы: цемент, бетон, стекло, кирпич | 23 | energy_prices −0.6, mortgage_market +0.5, gov_spending +0.4, logistics −0.4 | mining_metal_ores .4, power_utilities .3, wholesale_fuel .3 | construction_buildings .5, wholesale_construction_materials .3, construction_infrastructure .2 | цемент, бетон, кирпич, стекло, ЖБИ |
| `metallurgy` | Металлургия | 24 | fx_usd +0.5, energy_prices −0.5, sanctions −0.5, customs_tariffs −0.4, logistics −0.4 | mining_metal_ores .4, coal .3, power_utilities .2, transport_logistics .1 | wholesale_metals .35, construction_buildings .2, metal_products .2, machinery .15, construction_infrastructure .1 | сталь, металл, прокат, арматура, металлург, чугун, алюминий, медь |
| `metal_products` | Металлоизделия и металлоконструкции | 25 | gov_spending +0.4 | metallurgy .6, wholesale_metals .4 | construction_buildings .3, machinery .3, construction_infrastructure .2, wholesale_construction_materials .2 | металлоконструкция, метизы, изделие |
| `electronics` | Электроника, компьютеры, оптика | 26 | fx_cny −0.7, sanctions −0.6, customs_tariffs −0.4 | wholesale_tech_equipment .5, plastics_rubber .3, chemicals .2 | it_telecom .4, wholesale_tech_equipment .3, public_social .3 | электроника, микросхема, чип, сервер, смартфон |
| `electrical_equipment` | Электрооборудование | 27 | fx_cny −0.5, gov_spending +0.4 | metallurgy .4, wholesale_metals .3, electronics .3 | construction_specialized .3, power_utilities .3, machinery .2, wholesale_tech_equipment .2 | кабель, трансформатор, электрооборудование, двигатель |
| `machinery` | Машиностроение, ремонт и монтаж оборудования | 28, 33 | fx_cny −0.5, sanctions −0.5, key_rate −0.4, gov_spending +0.4 | metallurgy .4, metal_products .3, electrical_equipment .2, wholesale_tech_equipment .1 | oil_gas .2, agriculture .2, construction_infrastructure .2, mining_metal_ores .2, wholesale_tech_equipment .2 | станок, оборудование, машиностроение, спецтехника, комбайн |
| `automotive_manufacturing` | Автопром | 29 | consumer_demand +0.6, key_rate −0.5, fx_cny −0.5, customs_tariffs +0.4 | metallurgy .3, wholesale_tech_equipment .3, plastics_rubber .2, electrical_equipment .2 | auto_trade .7, transport_logistics .2, public_social .1 | автомобиль, автопром, автозавод, грузовик, утильсбор |
| `other_transport_equipment` | Вагоны, суда, авиатехника | 30 | gov_spending +0.6, sanctions −0.5 | metallurgy .4, electrical_equipment .3, machinery .3 | transport_logistics .7, public_social .3 | вагон, локомотив, судно, самолёт, верфь |
| `furniture_other_manufacturing` | Мебель и прочие изделия | 31, 32 | consumer_demand +0.5, mortgage_market +0.3 | wood_paper .5, plastics_rubber .2, metal_products .2, textile_apparel .1 | retail .6, wholesale_consumer_goods .4 | мебель, игрушки, ювелирный |
| `construction_buildings` | Строительство зданий, девелопмент | 41 | mortgage_market +0.9, key_rate −0.7, credit_conditions −0.5, labor_costs −0.5, gov_spending +0.3 | building_materials .3, wholesale_construction_materials .25, construction_specialized .2, wholesale_metals .15, electrical_equipment .1 | real_estate .5, finance_insurance .3, public_social .2 | застройщик, новостройка, жильё, ипотека, эскроу, девелопер, ДДУ |
| `construction_infrastructure` | Инфраструктурное строительство | 42 | gov_spending +0.9, key_rate −0.4, labor_costs −0.4 | building_materials .3, wholesale_metals .2, machinery .2, construction_specialized .2, wholesale_fuel .1 | public_social .6, oil_gas .2, power_utilities .2 | дорога, мост, трасса, инфраструктура, госконтракт, нацпроект |
| `construction_specialized` | Специализированные строительные работы | 43 | gov_spending +0.4, mortgage_market +0.4, labor_costs −0.5 | wholesale_construction_materials .4, building_materials .3, electrical_equipment .3 | construction_buildings .6, construction_infrastructure .4 | монтаж, отделка, подряд, субподряд, электромонтаж |
| `real_estate` | Операции с недвижимостью | 68 | key_rate −0.6, mortgage_market +0.5, consumer_demand +0.3 | construction_buildings .5, business_services .3, power_utilities .2 | retail .4, business_services .3, it_telecom .3 | недвижимость, аренда, торговый центр, склад, офис |
| `auto_trade` | Торговля автомобилями, запчастями, автосервис | 45 | customs_tariffs −0.8, fx_cny −0.6, key_rate −0.6, consumer_demand +0.6, credit_conditions −0.5 | automotive_manufacturing .5, wholesale_tech_equipment .2, transport_logistics .15, finance_insurance .15 | finance_insurance .4, transport_logistics .2, business_services .2, retail .2 | автомобиль, дилер, автосалон, утильсбор, автокредит, запчасть |
| `wholesale_agri_food` | Опт: сельхозсырьё и продукты питания | 46.2, 46.3 | logistics −0.5, consumer_demand +0.4, customs_tariffs −0.4, fx_cny −0.3 | agriculture .5, food_production .4, transport_logistics .1 | retail .5, food_production .3, hospitality .2 | зерно, продукты, мясо, сахар, экспорт зерна, пошлина |
| `wholesale_consumer_goods` | Опт: непродовольственные потребтовары (в т. ч. фарма 46.46) | 46.4 | consumer_demand +0.7, fx_cny −0.5, customs_tariffs −0.4, logistics −0.4 | pharma .3, textile_apparel .2, furniture_other_manufacturing .2, wholesale_other .2, electronics .1 | retail .8, public_social .2 | бытовая техника, одежда, косметика, аптечный, дистрибуция |
| `wholesale_tech_equipment` | Опт: ИКТ, машины и оборудование | 46.5, 46.6 | fx_cny −0.8, sanctions −0.6, cross_border_payments −0.5, customs_tariffs −0.4 | machinery .4, electronics .3, electrical_equipment .3 | public_social .2, business_services .2, it_telecom .2, construction_infrastructure .1, construction_buildings .1, agriculture .1, mining_metal_ores .1 | оборудование, спецтехника, поставка, импорт, станок, сервер |
| `wholesale_fuel` | Опт: топливо | 46.71 | oil_prices +0.6, tax_burden −0.5, logistics −0.4 | oil_refining .8, transport_logistics .2 | transport_logistics .4, agriculture .2, retail .2, construction_infrastructure .2 | топливо, бензин, дизель, биржа, АЗС, запрет экспорта |
| `wholesale_metals` | Опт: металлы и руды | 46.72 | customs_tariffs −0.5, key_rate −0.5, fx_cny −0.4, gov_spending +0.3, mortgage_market +0.3 | metallurgy .8, metal_products .1, transport_logistics .1 | construction_buildings .35, metal_products .2, machinery .2, construction_infrastructure .15, construction_specialized .1 | металлопрокат, арматура, сталь, металлобаза, лист, труба |
| `wholesale_construction_materials` | Опт: стройматериалы, лесоматериалы, сантехника | 46.73, 46.74 | mortgage_market +0.6, key_rate −0.5, gov_spending +0.3 | building_materials .5, wood_paper .3, metal_products .2 | construction_buildings .4, construction_specialized .4, retail .2 | стройматериалы, цемент, пиломатериал, сантехника, сухие смеси |
| `wholesale_chemicals` | Опт: химическая продукция и удобрения | 46.75 | logistics −0.4, customs_tariffs −0.3, fx_usd −0.3 | chemicals .8, transport_logistics .2 | agriculture .4, plastics_rubber .3, construction_specialized .3 | удобрения, химикаты, реагенты, полимеры |
| `wholesale_other` | Прочий опт и торговые агенты | 46 (запасной для неразобранных кодов опта), 46.1, 46.76, 46.77, 46.9 | consumer_demand +0.3, fx_cny −0.3 | food_production .25, wholesale_consumer_goods .25, textile_apparel .2, electronics .15, plastics_rubber .15 | retail .7, hospitality .3 | опт, дистрибьютор, торговый дом, поставка |
| `retail` | Розничная торговля | 47 | consumer_demand +0.9, inflation −0.4, labor_costs −0.4, key_rate −0.3 | wholesale_agri_food .3, wholesale_consumer_goods .3, food_production .2, wholesale_other .2 | — (физлица) | ритейл, магазин, розница, торговая сеть, маркетплейс |
| `transport_logistics` | Транспорт, склады, логистика | 49, 50, 51, 52, 53 | oil_prices −0.6, logistics +0.4, sanctions −0.3 | wholesale_fuel .4, auto_trade .2, machinery .2, other_transport_equipment .2 | retail .3, wholesale_other .3, metallurgy .2, oil_gas .2 | перевозка, логистика, грузоперевозки, РЖД, фрахт, контейнер, порт |
| `hospitality` | Гостиницы и общепит | 55, 56 | consumer_demand +0.8, labor_costs −0.5, inflation −0.4 | wholesale_agri_food .5, food_production .3, real_estate .2 | — | ресторан, гостиница, отель, общепит, туризм |
| `it_telecom` | ИТ, связь, медиа | 58–63 | sanctions −0.4, fx_usd −0.3, tax_burden −0.3 | electronics .4, wholesale_tech_equipment .4, real_estate .2 | finance_insurance .3, public_social .3, retail .2, business_services .2 | связь, оператор, ИТ, софт, интернет, дата-центр |
| `finance_insurance` | Финансы, страхование, лизинговые компании | 64, 65, 66 | key_rate −0.5, credit_conditions −0.5 | it_telecom .4, business_services .4, real_estate .2 | — | банк, лизинг, страхование, кредит |
| `business_services` | Профессиональные и административные услуги, аренда | 69–75, 77–82 | labor_costs −0.5, tax_burden −0.3 | real_estate .4, it_telecom .4, transport_logistics .2 | finance_insurance .2, it_telecom .2, retail .2, construction_buildings .2, public_social .2 | консалтинг, аудит, аренда техники, клининг, охрана |
| `public_social` | Госуправление, образование, здравоохранение, культура | 84–93 | gov_spending +0.8 | business_services .3, construction_infrastructure .3, pharma .2, wholesale_consumer_goods .2 | — | бюджет, госзакупки, больница, школа, министерство |
| `other_services` | Прочие услуги | 94–99 | consumer_demand +0.5 | business_services .5, real_estate .5 | — | услуги, ремонт, бытовые |
| `unknown` | Не определено | — | — | — | — | — |

Диапазоны вроде `58–63` в YAML разворачиваются в отдельные префиксы (`58`, `59`, …, `63`). Веса — экспертная оценка. Они калибруются на офлайн-разметке (`12-quality.md`).

### 5.2 Факторы (`factors.yaml`)

```yaml
version: 1
factors:
  - id: key_rate
    name: Ключевая ставка ЦБ
    up_means: Ставка растёт или ожидания ужесточения денежно-кредитной политики
    risk_text: дороже обслуживание кредитов и лизинга, дороже новое финансирование
    opportunity_text: дешевле заёмные средства, проще рефинансировать долг
    macro_indicator: key_rate          # для get_macro; null если ряда нет
```

| id | Название | «Рост» означает | Ряд ЦБ |
|---|---|---|---|
| `key_rate` | Ключевая ставка | Ставка выше, ДКП жёстче | `key_rate` |
| `credit_conditions` | Условия кредитования | Банки ужесточают выдачу, растут надбавки и лимиты | — |
| `inflation` | Инфляция | Инфляция ускоряется | — |
| `fx_usd` | Курс доллара | Доллар дорожает к рублю | `fx_usd` |
| `fx_eur` | Курс евро | Евро дорожает | `fx_eur` |
| `fx_cny` | Курс юаня | Юань дорожает | `fx_cny` |
| `fx_try` | Курс лиры | Лира дорожает | `fx_try` |
| `fx_aed` | Курс дирхама | Дирхам дорожает | `fx_aed` |
| `fx_inr` | Курс рупии | Рупия дорожает | `fx_inr` |
| `fx_kzt` | Курс тенге | Тенге дорожает | `fx_kzt` |
| `sanctions` | Санкционное давление | Новые ограничения, вторичные санкции | — |
| `cross_border_payments` | Международные платежи | Платежи за рубеж затрудняются: отказы банков, комиссии, сроки | — |
| `customs_tariffs` | Пошлины и сборы на ввоз и вывоз | Пошлины, утильсбор, квоты и барьеры растут | — |
| `logistics` | Логистика | Перевозки дорожают или затрудняются | — |
| `tax_burden` | Налоговая нагрузка | Налоги и сборы растут | — |
| `gov_spending` | Госрасходы и госзаказ | Госрасходы и госзаказ растут | — |
| `consumer_demand` | Потребительский спрос | Спрос растёт | — |
| `mortgage_market` | Ипотека | Условия ипотеки улучшаются, программы расширяются | — |
| `energy_prices` | Тарифы на энергию | Тарифы на электроэнергию и газ растут | — |
| `oil_prices` | Нефть | Цены на нефть растут | — |
| `labor_costs` | Рынок труда | Дефицит кадров, рост зарплат | — |
| `payment_discipline` | Платёжная дисциплина | Растут неплатежи и просрочка в экономике | — |

Направление влияния фактора на компанию: `d` — направление в событии (+1 рост, −1 снижение), `σ` — знак экспозиции компании. Если `d·σ > 0`, это возможность (`opportunity_text`), если `d·σ < 0` — риск (`risk_text`).

### 5.3 Эффекты события на отрасль (`effects.yaml`)

| id | Смысл |
|---|---|
| `prices_up` | Цены на продукцию отрасли растут |
| `prices_down` | Цены на продукцию отрасли снижаются |
| `demand_up` | Спрос на продукцию отрасли растёт |
| `demand_down` | Спрос на продукцию отрасли падает |
| `supply_down` | Выпуск или поставки отрасли сокращаются: запреты, аварии, дефицит |
| `supply_up` | Выпуск или предложение отрасли растёт |
| `costs_up` | Издержки отрасли растут: налоги, сборы, сырьё, тарифы |
| `costs_down` | Издержки отрасли снижаются |
| `regulation_tighter` | Регулирование ужесточается: требования, запреты, проверки |
| `support_measures` | Господдержка: субсидии, льготы, госзаказ |

Матрица «канал × эффект → направление, сила, механизм» — в `07-ranking.md` §3. Она хранится в том же файле `effects.yaml` в поле `matrix`:

```yaml
version: 1
effects:
  - {id: prices_up, meaning: Цены на продукцию отрасли растут}
  # … остальные 9 эффектов из таблицы выше
matrix:
  own:
    prices_up: {direction: opportunity, strength: 1.0, mechanism: "рост цен реализации"}
    # … все 10 эффектов
  supply:
    prices_up: {direction: risk, strength: 1.0, mechanism: "рост закупочных цен → себестоимость"}
  demand:
    prices_up: {direction: opportunity, strength: 0.5, mechanism: "у покупателей растёт выручка → платёжеспособность"}
```

### 5.4 Типы событий (`event_types.yaml`)

`monetary_policy` (решения и сигналы ЦБ), `fx_market`, `inflation_data`, `tariffs_customs`, `sanctions`, `tax_change`, `regulation`, `government_support`, `government_procurement`, `commodity_prices`, `supply_disruption`, `logistics`, `demand_shift`, `industry_statistics`, `corporate_event` (M&A, банкротства и смена собственников крупных игроков), `credit_market`, `real_estate_market`, `energy_market`, `labor_market`, `trade_policy` (экспорт и импорт, квоты, запреты), `geopolitics`, `natural_disaster`, `other`.

У каждого типа есть `name` (рус.) и `default_factors` — подсказка для промпта разметки:

```yaml
version: 1
event_types:
  - {id: monetary_policy, name: Решения и сигналы ЦБ по ставке, default_factors: [key_rate, credit_conditions]}
  - {id: tariffs_customs, name: Пошлины, утильсбор и таможенные меры, default_factors: [customs_tariffs]}
  # … остальные типы
```

### 5.5 Страны (`countries.yaml`)

```yaml
version: 1
countries:
  - iso2: CN
    names: [китай, кнр, китайская народная республика]
    currencies: [CNY, USD]
    payment_friction: high        # low | medium | high
    sanctions_scrutiny: high      # low | medium | high
```

Минимальный набор: CN, HK, TR, AE, IN, KZ, BY, UZ, KG, AM, GE, AZ, IR, VN, TH, MY, ID, KR, JP, DE, IT, FR, NL, PL, US, GB, EG, SA, BR, RS, MN. Сопоставление строки ФНС: нормализовать (нижний регистр, `ё` → `е`, без лишних пробелов и кавычек), затем искать точное совпадение с `names` и `iso2`. Нет совпадения — `country_iso2=NULL`, строка уходит в отчёт `validate`.

Факторы валют считаются только для отслеживаемых валют (USD, EUR, CNY, TRY, AED, INR, KZT). Страна, чья валюта не отслеживается, даёт экспозицию к `fx_usd` с весом ×0.5 как к валюте расчётов.

## 6. Производные таблицы

Все производные таблицы считаются **только для целевых компаний** (`target_companies`).

### 6.1 Отрасль контрагента (каскад)

Порядок источников, у каждого своя уверенность:

1. `companies.okved` по ключу контрагента (`counterparty_key`) → `method='companies_okved'`, `confidence=1.0`.
2. `payments.counterparty_okved` → `payments_okved`, `0.9`.
3. Ключевые слова в `counterparty_name` (леммы против `keywords` отраслей; минимум одно совпадение, выигрывает отрасль с наибольшим числом совпадений, при ничьей — `unknown`) → `name_keywords`, `0.6`. Считается в Python и пишется в `name_industry(counterparty_id, industry_id)`.
4. Иначе `unknown`, `0.0`.

```sql
CREATE TABLE counterparty_industry AS
WITH cp AS (
  SELECT counterparty_id,
         any_value(counterparty_name)  AS name,
         any_value(counterparty_okved) AS okved_p
  FROM payments
  WHERE company_id IN (SELECT company_id FROM target_companies)
  GROUP BY counterparty_id
)
SELECT cp.counterparty_id, cp.name,
       COALESCE(o1.industry_id, o2.industry_id, ni.industry_id, 'unknown') AS industry_id,
       CASE WHEN o1.industry_id IS NOT NULL THEN 'companies_okved'
            WHEN o2.industry_id IS NOT NULL THEN 'payments_okved'
            WHEN ni.industry_id IS NOT NULL THEN 'name_keywords'
            ELSE 'unknown' END AS method,
       CASE WHEN o1.industry_id IS NOT NULL THEN 1.0
            WHEN o2.industry_id IS NOT NULL THEN 0.9
            WHEN ni.industry_id IS NOT NULL THEN 0.6
            ELSE 0.0 END AS confidence
FROM cp
LEFT JOIN companies c       ON c.company_id = cp.counterparty_id      -- или c.inn = …, по counterparty_key
LEFT JOIN okved_industry o1 ON o1.okved = c.okved
LEFT JOIN okved_industry o2 ON o2.okved = cp.okved_p
LEFT JOIN name_industry ni  ON ni.counterparty_id = cp.counterparty_id;
```

### 6.2 Потоки по отраслям и покрытие

`weight` — выбранная база (`amount_rub`, `tx_count` или `1` на связь).

```sql
CREATE TABLE flows_by_industry AS
WITH base AS (
  SELECT p.company_id, p.direction, ci.industry_id,
         SUM(COALESCE(p.amount_rub, 0))        AS amount_rub,
         SUM(COALESCE(p.tx_count, 1))          AS tx_count,
         COUNT(DISTINCT p.counterparty_id)     AS n_counterparties,
         SUM(<weight_expr>)                    AS weight
  FROM payments p
  JOIN counterparty_industry ci USING (counterparty_id)
  WHERE p.company_id IN (SELECT company_id FROM target_companies)
  GROUP BY 1, 2, 3
)
SELECT *,
       weight / SUM(weight) OVER (PARTITION BY company_id, direction) AS share_total,
       CASE WHEN industry_id <> 'unknown' THEN
         weight / NULLIF(SUM(CASE WHEN industry_id <> 'unknown' THEN weight END)
                         OVER (PARTITION BY company_id, direction), 0)
       END AS share_known
FROM base;

CREATE TABLE coverage AS
SELECT company_id, direction, total_weight, known_weight,
       known_weight / NULLIF(total_weight, 0) AS coverage
FROM (
  SELECT company_id, direction,
         SUM(weight) AS total_weight,
         SUM(CASE WHEN industry_id <> 'unknown' THEN weight ELSE 0 END) AS known_weight
  FROM flows_by_industry GROUP BY 1, 2
);
```

Перед агрегацией исключаются платежи самому себе (`exclude_self`) и внутри группы (`exclude_intragroup`, если есть `group_id`).

### 6.3 Крупнейшие контрагенты

```sql
CREATE TABLE top_counterparties AS
SELECT * FROM (
  SELECT p.company_id, p.direction, p.counterparty_id,
         any_value(p.counterparty_name) AS name, ci.industry_id,
         SUM(<weight_expr>) AS weight,
         SUM(<weight_expr>) / SUM(SUM(<weight_expr>)) OVER (PARTITION BY p.company_id, p.direction) AS share,
         row_number() OVER (PARTITION BY p.company_id, p.direction ORDER BY SUM(<weight_expr>) DESC) AS rank
  FROM payments p JOIN counterparty_industry ci USING (counterparty_id)
  WHERE p.company_id IN (SELECT company_id FROM target_companies)
  GROUP BY p.company_id, p.direction, p.counterparty_id, ci.industry_id
) WHERE rank <= 50;
```

### 6.4 Экспозиция к факторам (`company_factors`)

Считается в Python (`data/factors.py`) по правилам. Итог по фактору — `min(1, сумма вкладов)`. Знак берётся из правила с наибольшим вкладом. Каждое правило добавляет строку в `reasons`.

| Фактор | Правило | Знак | Причина (текст в `reasons`) |
|---|---|---|---|
| все | `factor_sensitivity` основной отрасли (вес ×1.0) и дополнительных (×0.5) | из отрасли | «отрасль: Оптовая торговля металлами» |
| `key_rate` | +0.2 базово; +0.5 при `credit`; +0.3 при `leasing` | −1 | «есть кредит», «есть лизинг» |
| `credit_conditions` | +0.4 при `credit` | −1 | «есть кредит» |
| `fx_<cur>` | +0.7 за каждую страну ВЭД с этой валютой (`import` или `unknown`); +0.5 при `export` (знак +1) | −1 импорт, +1 экспорт | «ВЭД: Китай (импорт)» |
| `sanctions` | +0.4 при любом ВЭД; +0.2 если у страны `sanctions_scrutiny ≥ medium` | −1 | «ВЭД со странами повышенного внимания» |
| `cross_border_payments` | +0.6 при стране с `payment_friction=high`, +0.4 при `medium` | −1 | «платежи в Китай» |
| `customs_tariffs` | +0.6 при импорте; +0.3 при экспорте | −1 | «импорт» |
| `logistics` | +0.4 при любом ВЭД | −1 | «ВЭД» |
| `tax_burden` | +0.3 всем | −1 | «общий фактор» |
| `labor_costs`, `inflation` | +0.2 всем | −1 | «общий фактор» |
| `payment_discipline` | +0.2 всем; +0.3 если у крупнейшего покупателя доля > 20% | −1 | «концентрация покупателей: 27% у одного» |

Факторы с экспозицией ниже 0.15 в профиль не попадают (кроме общих).

### 6.5 Профили

`profiles(company_id VARCHAR PRIMARY KEY, profile_json VARCHAR, profile_version VARCHAR)` — по строке на целевую компанию. `profile_json` — сериализованный `CompanyProfile` (§7) **без** пользовательских правок. Правки накладывает `ProfileStore` при чтении.

## 7. Профиль компании

```python
# alfa_insight/data/models.py
from typing import Literal
from pydantic import BaseModel

Direction = Literal["out", "in"]                 # out = поставщики, in = покупатели

class IndustryShare(BaseModel):
    industry_id: str
    name: str
    share: float                                 # доля среди известных отраслей, 0..1
    share_total: float                           # доля от всего объёма, включая unknown
    n_counterparties: int

class FactorExposure(BaseModel):
    factor_id: str
    name: str
    exposure: float                              # 0..1
    sign: Literal[-1, 1]
    reasons: list[str]

class ProductInfo(BaseModel):
    has: bool
    amount_rub: float | None = None

class VedEntry(BaseModel):
    country_iso2: str | None
    country_name: str
    direction: Literal["import", "export", "unknown"]
    currencies: list[str]

class Feature(BaseModel):
    key: str                                     # см. таблицу ключей ниже
    label: str                                   # «Доля закупок у металлургии»
    value: str                                   # «34% (покрытие данных 90%)»
    source: Literal["data", "override", "prior"]

class CompanyProfile(BaseModel):
    company_id: str
    name: str
    inn: str | None
    okved: str | None
    industry_id: str
    industry_name: str
    secondary_industry_ids: list[str] = []
    region_code: str | None
    region_name: str | None
    revenue_rub: float | None
    revenue_bucket: Literal["15-30", "30-100", "100-500", "500+", "unknown"]
    is_client: bool
    group_id: str | None
    products: dict[str, ProductInfo]
    ved: list[VedEntry]
    suppliers_mix: list[IndustryShare]           # топ-10 по share, без unknown
    buyers_mix: list[IndustryShare]
    coverage: dict[Literal["supply", "demand"], float]
    direction_unknown: bool = False
    factor_exposure: list[FactorExposure]
    features: list[Feature]
    profile_version: str                         # sha1(profile_json без версии + overrides)
    data_profile: Literal["real", "synthetic"]
```

**Ключи признаков** (`Feature.key`) — закрытый набор шаблонов. Только на них агент может ссылаться в `client_features_used`:

| Шаблон ключа | Пример | Источник |
|---|---|---|
| `industry.main` | Основная отрасль: Оптовая торговля металлами (46.72) | data/override |
| `industry.secondary.<industry_id>` | Доп. отрасль: Металлоизделия | data |
| `region` | Регион: Москва | data |
| `revenue` | Выручка: 30–100 млрд ₽ | data |
| `products.<code>` | Продукт: кредит в Альфа-Банке | data/override |
| `ved.country.<ISO2>` | ВЭД: Китай (импорт) | data/override |
| `suppliers.<industry_id>` | Закупки у металлургии: 34% | data/prior |
| `buyers.<industry_id>` | Продажи строителям: 38% | data/prior |
| `coverage.supply`, `coverage.demand` | Покрытие данных о поставщиках: 90% | data |
| `factor.<factor_id>` | Чувствительность к ключевой ставке: высокая (есть кредит, есть лизинг) | data |
| `group` | Входит в группу компаний | data |
| `override.<field>` | Уточнено вами: экспорт в Казахстан | override |

**ProfileStore** (`data/profiles.py`):

```python
class ProfileStore:
    def __init__(self, duck: DuckReader, overrides: ProfileOverridesRepo, taxonomy: Taxonomy): ...
    def get(self, company_id: str) -> CompanyProfile           # кеш в памяти + правки, KeyError → NotFoundError
    def list_targets(self) -> list[CompanySummary]             # для входа в демо / jury
    def invalidate(self, company_id: str) -> None
    def apply_overrides(self, base: CompanyProfile, overrides: list[Override]) -> CompanyProfile
```

Правки (`profile_overrides.field`): `industry_id` (сменить основную отрасль), `ved` (список `{country_iso2, direction}`), `products` (словарь `code → has`), `notes` (свободный текст, попадает в контекст агента как `override.notes`). После правки факторы пересчитываются той же функцией `data/factors.py`, но на Python-модели, без DuckDB.

## 8. Синтетические данные

### 8.1 Требования

- Детерминированность: `alfa data synth --seed 42` всегда даёт одинаковые файлы (проверка хешем в тесте).
- Та же **логическая** схема (§2), физические имена колонок совпадают с логическими. Маппинг `data_mapping.synthetic.yaml` тождественный.
- Распределения похожи на реальные (по исходному анализу):

| Параметр | Значение |
|---|---|
| Всего компаний | 3000 (`--companies`) |
| Целевых (выручка ≥ 15 млрд) | ≈40, включая 6 демо |
| Клиенты среди целевых | 94% |
| Отрасли целевых | опт 54% (по видам: металлы, топливо, стройматериалы, продукты, потребтовары, техника), строительство 17%, автодилеры 9%, остальное 20% |
| Кредит / лизинг среди целевых | 43% / 62% |
| ВЭД заполнен | 50% целевых: Китай 45%, Турция 15%, ОАЭ 12%, Индия 8%, Казахстан 8%, прочие 12% |
| Контрагентов у целевой | 150–600 |
| Доля контрагентов вне таблицы компаний | 15% (только название; проверка каскада §6.1) |
| Суммы | логнормальные, масштаб от выручки; входящие ≈ выручке, исходящие ≈ 85% выручки |

- Контрагенты выбираются по `typical_suppliers` и `typical_buyers` отрасли с шумом Дирихле (α=2), чтобы доли были правдоподобными, но не одинаковыми.
- Названия **вымышленные**: `ООО «{корень}{суффикс}»` из словарей по отраслям («Металл», «Сталь», «Агро», «Строй», «Авто», «Фарм», «Нефте», «Логистик» и т. п.) × («Трейд», «Снаб», «Пром», «Групп», «Инвест», «Ресурс») + город. Совпадение с реальными брендами исключается стоп-листом.
- `company_id` вида `SYN-000123`, `inn` — 10 цифр с кодом региона `00` (не существует) и корректной контрольной цифрой.

### 8.2 Файлы

`data/synthetic/companies.csv`, `products.csv`, `ved.csv`, `payments.csv` (UTF-8, разделитель `,`, точка в десятичных). Размер всех файлов не больше 8 МБ.

### 8.3 Демо-компании (`config/demo.yaml`)

```yaml
version: 1
companies:
  - company_id: SYN-DEMO-01
    name: ООО «ТД Северный Металл»
    okved: "46.72.2"
    region_code: RU-MOW
    region_name: Москва
    revenue_rub: 48_000_000_000
    products: {credit: 3_500_000_000, leasing: 400_000_000}
    ved: [{country: CN, direction: import}]
    suppliers_mix: {metallurgy: 0.62, wholesale_metals: 0.12, transport_logistics: 0.08, business_services: 0.05, unknown: 0.13}
    buyers_mix: {construction_buildings: 0.38, metal_products: 0.18, machinery: 0.17, construction_infrastructure: 0.12, construction_specialized: 0.10, unknown: 0.05}
    story: Металлотрейдер. Цены и пошлины на прокат, спрос строителей, ставка (склад на кредите), юань
    default_role: owner
  - company_id: SYN-DEMO-02
    name: ГК «Волга-Строй»
    okved: "41.20"
    region_code: RU-SAM
    region_name: Самарская область
    revenue_rub: 32_000_000_000
    products: {credit: 9_000_000_000, leasing: 600_000_000}
    ved: []
    suppliers_mix: {metallurgy: 0.34, building_materials: 0.22, construction_specialized: 0.15, wholesale_construction_materials: 0.14, electrical_equipment: 0.05, unknown: 0.10}
    buyers_mix: {finance_insurance: 0.55, real_estate: 0.25, public_social: 0.10, unknown: 0.10}
    story: Девелопер. Ипотечные программы, ключевая ставка, проектное финансирование, цены на арматуру и цемент
    default_role: cfo
  - company_id: SYN-DEMO-03
    name: ООО «Автомир Юг»
    okved: "45.11"
    region_code: RU-KDA
    region_name: Краснодарский край
    revenue_rub: 21_000_000_000
    products: {credit: 2_000_000_000}
    ved: [{country: CN, direction: import}]
    suppliers_mix: {automotive_manufacturing: 0.45, wholesale_tech_equipment: 0.25, transport_logistics: 0.10, finance_insurance: 0.08, unknown: 0.12}
    buyers_mix: {finance_insurance: 0.45, transport_logistics: 0.15, business_services: 0.15, unknown: 0.25}
    story: Дилер китайских марок. Утильсбор, пошлины, юань, автокредиты и ставка
    default_role: cfo
  - company_id: SYN-DEMO-04
    name: ООО «АгроТрейд Восток»
    okved: "46.21"
    region_code: RU-NVS
    region_name: Новосибирская область
    revenue_rub: 18_000_000_000
    products: {credit: 1_200_000_000, leasing: 150_000_000}
    ved: [{country: CN, direction: export}, {country: KZ, direction: export}]
    suppliers_mix: {agriculture: 0.70, transport_logistics: 0.15, wholesale_fuel: 0.05, unknown: 0.10}
    buyers_mix: {food_production: 0.40, wholesale_agri_food: 0.30, unknown: 0.30}
    story: Экспортёр зерна. Экспортные пошлины и квоты, логистика на восток, юань, платежи из Китая
    default_role: treasurer
  - company_id: SYN-DEMO-05
    name: АО «ФармДистрибуция»
    okved: "46.46"
    region_code: RU-SPE
    region_name: Санкт-Петербург
    revenue_rub: 27_000_000_000
    products: {credit: 1_500_000_000}
    ved: [{country: IN, direction: import}, {country: CN, direction: import}]
    suppliers_mix: {pharma: 0.55, wholesale_chemicals: 0.10, transport_logistics: 0.10, unknown: 0.25}
    buyers_mix: {retail: 0.60, public_social: 0.30, unknown: 0.10}
    story: Дистрибьютор лекарств. Рупия и юань, маркировка и регулирование, госзакупки
    default_role: treasurer
  - company_id: SYN-DEMO-06
    name: ООО «Топливная компания Регион»
    okved: "46.71"
    region_code: RU-SVE
    region_name: Свердловская область
    revenue_rub: 60_000_000_000
    products: {credit: 4_000_000_000, leasing: 1_200_000_000}
    ved: []
    suppliers_mix: {oil_refining: 0.80, transport_logistics: 0.12, unknown: 0.08}
    buyers_mix: {transport_logistics: 0.35, agriculture: 0.20, construction_infrastructure: 0.15, retail: 0.15, unknown: 0.15}
    story: Оптовик топлива. Биржевые цены, запрет экспорта бензина, демпфер, нефть
    default_role: owner
roles:
  cfo: {name: Финансовый директор, short: CFO}
  treasurer: {name: Казначей, short: Казначейство}
  owner: {name: Собственник, short: Собственник}
precompute:
  top_k: 5
  min_score: 0.15
```

Генератор создаёт демо-компании точно по этим долям (с шумом ±1 п. п. и контрагентами под нужные отрасли), остальных — случайно. При `DATA_PROFILE=real` демо-компании берутся из `config/demo.real.yaml` (6 реальных целевых `company_id`, выбираются в T5.5). Этот файл в `.gitignore`.

## 9. SQLite (`data/runtime/app.sqlite`): полная DDL

Файл `backend/alfa_insight/db/migrations/0001_init.sql`. Применяется командой `alfa db migrate` (идемпотентно, учёт в `schema_migrations`). Новые изменения — только новыми файлами `000N_*.sql`.

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
);

CREATE TABLE kv (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);

-- ───────── События (кластеры новостей) ─────────
CREATE TABLE events (
  id                  INTEGER PRIMARY KEY,
  title               TEXT NOT NULL,
  summary             TEXT NOT NULL,
  event_type          TEXT NOT NULL,
  importance          INTEGER NOT NULL CHECK (importance BETWEEN 1 AND 5),
  horizon             TEXT NOT NULL CHECK (horizon IN ('days','weeks','months','quarters')),
  first_seen_at       TEXT NOT NULL,
  last_seen_at        TEXT NOT NULL,
  news_count          INTEGER NOT NULL DEFAULT 1,
  publisher_count     INTEGER NOT NULL DEFAULT 1,
  max_trust           REAL NOT NULL,
  tag_confidence      REAL NOT NULL DEFAULT 0.5,
  lead_news_id        INTEGER,
  geo_json            TEXT NOT NULL DEFAULT '[]',
  key_lemmas          TEXT NOT NULL DEFAULT '[]',   -- топ-40 лемм для кластеризации (06 §9)
  visibility          TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','private')),
  owner_company_id    TEXT,
  injection_suspected INTEGER NOT NULL DEFAULT 0,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
CREATE INDEX idx_events_last_seen ON events(last_seen_at);

CREATE TABLE event_industries (
  event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  industry_id TEXT NOT NULL,
  effect      TEXT NOT NULL,
  impact      REAL NOT NULL,          -- 0..1
  confidence  REAL NOT NULL,          -- 0..1
  rationale   TEXT,
  PRIMARY KEY (event_id, industry_id, effect)
);
CREATE TABLE event_factors (
  event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  factor_id  TEXT NOT NULL,
  direction  INTEGER NOT NULL CHECK (direction IN (-1, 1)),
  impact     REAL NOT NULL,
  confidence REAL NOT NULL,
  rationale  TEXT,
  PRIMARY KEY (event_id, factor_id)
);
CREATE VIRTUAL TABLE events_fts USING fts5(title_lemmas, summary_lemmas, tokenize = 'unicode61 remove_diacritics 2');

-- ───────── Новости ─────────
CREATE TABLE news (
  id               INTEGER PRIMARY KEY,
  source_id        TEXT NOT NULL,              -- id из sources.yaml | 'seed' | 'user'
  origin           TEXT NOT NULL CHECK (origin IN ('rss','seed','user')),
  external_id      TEXT,                       -- guid из RSS; seed_id для seed
  url              TEXT,
  url_hash         TEXT UNIQUE,                -- sha1(нормализованный URL); NULL для текста пользователя
  title            TEXT NOT NULL,
  rss_summary      TEXT,
  body             TEXT,
  body_source      TEXT CHECK (body_source IN ('full','rss_summary','user','seed')),
  publisher        TEXT NOT NULL,
  trust            REAL NOT NULL,              -- 0..1 из sources.yaml
  published_at     TEXT NOT NULL,
  fetched_at       TEXT NOT NULL,
  rss_categories   TEXT NOT NULL DEFAULT '[]',
  content_hash     TEXT,
  simhash          INTEGER,
  prefilter_score  REAL,
  status           TEXT NOT NULL DEFAULT 'new'
                   CHECK (status IN ('new','extracted','filtered_out','duplicate','tagged','clustered','failed')),
  attempts         INTEGER NOT NULL DEFAULT 0,
  duplicate_of     INTEGER REFERENCES news(id),
  injection_flags  TEXT NOT NULL DEFAULT '[]',
  error            TEXT,
  event_id         INTEGER REFERENCES events(id),
  owner_company_id TEXT,
  created_at       TEXT NOT NULL
);
CREATE INDEX idx_news_status    ON news(status, published_at);
CREATE INDEX idx_news_published ON news(published_at);
CREATE INDEX idx_news_event     ON news(event_id);
CREATE UNIQUE INDEX idx_news_external ON news(source_id, external_id) WHERE external_id IS NOT NULL;

CREATE TABLE news_tags (
  news_id              INTEGER PRIMARY KEY REFERENCES news(id) ON DELETE CASCADE,
  model                TEXT NOT NULL,
  prompt_version       TEXT NOT NULL,
  is_business_relevant INTEGER NOT NULL,
  event_type           TEXT NOT NULL,
  importance           INTEGER NOT NULL,
  horizon              TEXT NOT NULL,
  summary              TEXT NOT NULL,
  payload_json         TEXT NOT NULL,          -- NewsTagging целиком
  tagged_at            TEXT NOT NULL
);
CREATE TABLE news_industries (
  news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
  industry_id TEXT NOT NULL, effect TEXT NOT NULL,
  impact REAL NOT NULL, confidence REAL NOT NULL, rationale TEXT,
  PRIMARY KEY (news_id, industry_id, effect)
);
CREATE TABLE news_factors (
  news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
  factor_id TEXT NOT NULL, direction INTEGER NOT NULL CHECK (direction IN (-1, 1)),
  impact REAL NOT NULL, confidence REAL NOT NULL, rationale TEXT,
  PRIMARY KEY (news_id, factor_id)
);
CREATE TABLE news_geo (
  news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
  geo TEXT NOT NULL,                           -- ISO2 страны или ISO 3166-2:RU
  PRIMARY KEY (news_id, geo)
);
CREATE TABLE news_entities (
  news_id INTEGER NOT NULL REFERENCES news(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('company','gov','person','country','org')),
  name TEXT NOT NULL,
  PRIMARY KEY (news_id, kind, name)
);
CREATE VIRTUAL TABLE news_fts USING fts5(title_lemmas, body_lemmas, tokenize = 'unicode61 remove_diacritics 2');

-- ───────── Аналитика Альфа-Банка ─────────
CREATE TABLE research_docs (
  id           INTEGER PRIMARY KEY,
  slug         TEXT NOT NULL UNIQUE,
  title        TEXT NOT NULL,
  published_at TEXT,
  file_name    TEXT NOT NULL,
  sha256       TEXT NOT NULL UNIQUE,
  pages        INTEGER NOT NULL,
  url          TEXT,
  status       TEXT NOT NULL DEFAULT 'parsed' CHECK (status IN ('parsed','extracted','failed')),
  processed_at TEXT NOT NULL
);
CREATE TABLE research_chunks (
  id        INTEGER PRIMARY KEY,
  doc_id    INTEGER NOT NULL REFERENCES research_docs(id) ON DELETE CASCADE,
  source_id TEXT NOT NULL UNIQUE,              -- alfa:{slug}:p{page}:c{n}
  page      INTEGER NOT NULL,
  chunk_no  INTEGER NOT NULL,
  kind      TEXT NOT NULL CHECK (kind IN ('text','table','chart')),
  heading   TEXT,
  text      TEXT NOT NULL
);
CREATE TABLE research_items (
  id              INTEGER PRIMARY KEY,
  chunk_id        INTEGER NOT NULL REFERENCES research_chunks(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL CHECK (kind IN ('fact','forecast','position')),
  statement       TEXT NOT NULL,
  indicator       TEXT, value TEXT, unit TEXT, period TEXT,
  industries_json TEXT NOT NULL DEFAULT '[]',
  factors_json    TEXT NOT NULL DEFAULT '[]',
  confidence      REAL NOT NULL
);
CREATE VIRTUAL TABLE research_fts USING fts5(heading_lemmas, text_lemmas, tokenize = 'unicode61 remove_diacritics 2');

-- ───────── Макро ─────────
CREATE TABLE macro_series (
  indicator  TEXT NOT NULL,                    -- key_rate | fx_usd | fx_eur | fx_cny | fx_try | fx_aed | fx_inr | fx_kzt
  date       TEXT NOT NULL,                    -- YYYY-MM-DD
  value      REAL NOT NULL,                    -- % для ставки; ₽ за 1 единицу валюты
  source     TEXT NOT NULL CHECK (source IN ('cbr','snapshot')),
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (indicator, date)
);

-- ───────── Ранжирование ─────────
CREATE TABLE rankings (
  company_id      TEXT NOT NULL,
  event_id        INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('cfo','treasurer','owner')),
  score           REAL NOT NULL,
  relevance       REAL NOT NULL,
  rerank_score    REAL,
  direction       TEXT NOT NULL CHECK (direction IN ('risk','opportunity','mixed')),
  impact_level    TEXT NOT NULL CHECK (impact_level IN ('low','medium','high','critical')),
  chain_preview   TEXT,
  components_json TEXT NOT NULL,
  chain_json      TEXT NOT NULL,
  profile_version TEXT NOT NULL,
  computed_at     TEXT NOT NULL,
  PRIMARY KEY (company_id, event_id, role)
);
CREATE INDEX idx_rankings_feed ON rankings(company_id, role, score DESC);

-- ───────── Агент ─────────
CREATE TABLE agent_runs (
  id            TEXT PRIMARY KEY,              -- run_<ulid>
  kind          TEXT NOT NULL CHECK (kind IN ('insight','analyze','chat')),
  mode          TEXT NOT NULL CHECK (mode IN ('pipeline','agentic')),
  status        TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
  priority      TEXT NOT NULL CHECK (priority IN ('interactive','precompute','background')),
  company_id    TEXT NOT NULL,
  role          TEXT,
  event_id      INTEGER REFERENCES events(id),
  insight_id    TEXT,
  session_id    TEXT,
  input_json    TEXT NOT NULL DEFAULT '{}',
  result_json   TEXT,
  error_code    TEXT,
  error_message TEXT,
  tokens_in     INTEGER NOT NULL DEFAULT 0,
  tokens_out    INTEGER NOT NULL DEFAULT 0,
  cost_rub      REAL NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT
);
CREATE INDEX idx_runs_queue ON agent_runs(status, priority, created_at);
CREATE INDEX idx_runs_pair  ON agent_runs(company_id, event_id, kind, status);

CREATE TABLE trace_events (
  run_id       TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  ts           TEXT NOT NULL,
  type         TEXT NOT NULL,                  -- см. 08-agent.md §11
  phase        TEXT NOT NULL,
  title        TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok','warn','error','info')),
  payload_json TEXT NOT NULL DEFAULT '{}',
  model        TEXT,
  tokens_in    INTEGER,
  tokens_out   INTEGER,
  cost_rub     REAL,
  latency_ms   INTEGER,
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE insights (
  id                TEXT PRIMARY KEY,          -- ins_<ulid>
  company_id        TEXT NOT NULL,
  event_id          INTEGER NOT NULL REFERENCES events(id),
  run_id            TEXT NOT NULL REFERENCES agent_runs(id),
  prompt_version    TEXT NOT NULL,
  profile_version   TEXT NOT NULL,
  status            TEXT NOT NULL CHECK (status IN ('published','needs_review','rejected')),
  headline          TEXT NOT NULL,
  direction         TEXT NOT NULL,
  impact_level      TEXT NOT NULL,
  confidence        REAL NOT NULL,
  confidence_level  TEXT NOT NULL CHECK (confidence_level IN ('low','medium','high')),
  payload_json      TEXT NOT NULL,             -- Insight (08-agent.md §8.2)
  verification_json TEXT NOT NULL,             -- VerificationReport
  model             TEXT NOT NULL,
  cost_rub          REAL NOT NULL,
  created_at        TEXT NOT NULL,
  reviewed_at       TEXT,
  review_note       TEXT,
  UNIQUE (company_id, event_id, prompt_version, profile_version)
);
CREATE INDEX idx_insights_company ON insights(company_id, created_at DESC);

CREATE TABLE sources (
  id           TEXT PRIMARY KEY,               -- формат id — 08-agent.md §4
  kind         TEXT NOT NULL CHECK (kind IN ('news','alfa','cbr','client_data','user_input')),
  company_id   TEXT,                           -- только для client_data и user_input (проверка доступа)
  title        TEXT NOT NULL,
  publisher    TEXT,
  url          TEXT,
  published_at TEXT,
  excerpt      TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL
);
CREATE TABLE insight_sources (
  insight_id TEXT NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
  source_id  TEXT NOT NULL REFERENCES sources(id),
  PRIMARY KEY (insight_id, source_id)
);

-- ───────── Чат ─────────
CREATE TABLE chat_messages (
  id           INTEGER PRIMARY KEY,
  thread_id    TEXT NOT NULL,
  insight_id   TEXT NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
  company_id   TEXT NOT NULL,
  session_id   TEXT NOT NULL,
  role         TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content_json TEXT NOT NULL,
  run_id       TEXT,
  created_at   TEXT NOT NULL
);
CREATE INDEX idx_chat_thread ON chat_messages(thread_id, id);

-- ───────── Обратная связь, правки, заявки ─────────
CREATE TABLE feedback (
  id         INTEGER PRIMARY KEY,
  insight_id TEXT NOT NULL REFERENCES insights(id) ON DELETE CASCADE,
  company_id TEXT NOT NULL,
  role       TEXT NOT NULL,
  session_id TEXT NOT NULL,
  useful     INTEGER NOT NULL CHECK (useful IN (0, 1)),
  reason     TEXT CHECK (reason IN ('not_relevant','already_known','wrong_facts','too_generic','unclear',
                                    'useful_action','useful_risk','other')),
  comment    TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (insight_id, session_id)
);
CREATE TABLE ui_events (
  id           INTEGER PRIMARY KEY,
  session_id   TEXT NOT NULL,
  company_id   TEXT NOT NULL,
  type         TEXT NOT NULL CHECK (type IN ('feed_view','insight_open','source_open','trace_open',
                                             'chat_open','brief_view','analyze_submit','product_open')),
  insight_id   TEXT,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at   TEXT NOT NULL
);
CREATE TABLE profile_overrides (
  company_id TEXT NOT NULL,
  field      TEXT NOT NULL CHECK (field IN ('industry_id','ved','products','notes')),
  value_json TEXT NOT NULL,
  session_id TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (company_id, field)
);
CREATE TABLE leads (
  id         INTEGER PRIMARY KEY,
  company_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  insight_id TEXT,
  comment    TEXT,
  created_at TEXT NOT NULL
);

-- ───────── LLM ─────────
CREATE TABLE llm_cache (
  key            TEXT PRIMARY KEY,             -- 04-llm.md §6
  task           TEXT NOT NULL,
  model          TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  request_json   TEXT NOT NULL,
  response_json  TEXT NOT NULL,
  tokens_in      INTEGER NOT NULL,
  tokens_out     INTEGER NOT NULL,
  cost_rub       REAL NOT NULL,
  hits           INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL,
  last_hit_at    TEXT
);
CREATE TABLE llm_calls (
  id            INTEGER PRIMARY KEY,
  ts            TEXT NOT NULL,
  budget_day    TEXT NOT NULL,                 -- YYYY-MM-DD по BUDGET_TZ
  task          TEXT NOT NULL,
  model         TEXT NOT NULL,
  priority      TEXT NOT NULL,
  run_id        TEXT,
  cached        INTEGER NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('ok','error','budget_blocked','invalid_output')),
  tokens_in     INTEGER NOT NULL DEFAULT 0,
  tokens_out    INTEGER NOT NULL DEFAULT 0,
  cost_rub      REAL NOT NULL DEFAULT 0,
  latency_ms    INTEGER,
  base_url_kind TEXT CHECK (base_url_kind IN ('primary','fallback')),
  error         TEXT
);
CREATE INDEX idx_llm_calls_day ON llm_calls(budget_day, priority);
```

## 10. Проверка данных (`alfa data validate`)

Пишет отчёт в stdout (таблица), в `data/runtime/data_quality.json` и в DuckDB `data_quality(check, value, status, details)`. Статусы: `ok`, `warn`, `error`. Код возврата ненулевой при хотя бы одном `error`.

| Проверка | `warn`, если | `error`, если |
|---|---|---|
| Строк в каждой таблице | — | 0 |
| Целевых компаний | вне 80–150 при `real` | 0 |
| Доля клиентов среди целевых | < 80% | — |
| Распределение отраслей целевых (топ-10) | `unknown` > 10% | `unknown` > 40% |
| Доля целевых с кредитом и лизингом | — | — (для сверки с 43% и 62%) |
| Заполненность ВЭД и топ стран | нераспознанных стран > 5% | — |
| Доля целевых с платежами | < 90% | < 50% |
| Покрытие отраслей контрагентов, медиана по целевым | < 0.6 | < 0.3 (для `real` — < 0.15, см. §3.5) |
| Баланс направлений `in` / `out` | одна сторона < 10% | одной стороны нет |
| Платежи с пустой или отрицательной суммой | > 5% | — |
| Платежи самому себе | > 0 (удаляются) | — |
| Выбранный `weight_basis` | не `amount` | — |
| Дубликаты `company_id` | > 0 в исходнике (полные дубли схлопнуты, неоднозначные id исключены) | > 0 после сборки |

Отчёт на реальных данных должен воспроизвести цифры из исходного плана (115 / 108 / 62 / 43% / 62% / 1,38 млн / 113). Если не воспроизводит — разобраться до перехода к этапу 3.
