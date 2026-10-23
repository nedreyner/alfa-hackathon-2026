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
