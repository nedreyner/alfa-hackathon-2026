-- Ключ кеша у вызова: экспорт кеша по прогонам (`alfa llm cache export --runs`).
ALTER TABLE llm_calls ADD COLUMN cache_key TEXT;
CREATE INDEX idx_llm_calls_run ON llm_calls(run_id);
