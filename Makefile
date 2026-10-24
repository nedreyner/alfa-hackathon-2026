.PHONY: setup check test data seed dev-api dev-worker dev-web openapi up down eval notices

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

# THIRD_PARTY_NOTICES.md: рантайм-зависимости Python (без dev) и production-зависимости JS
notices:
	cd backend && UV_PROJECT_ENVIRONMENT=$(CURDIR)/.notices-venv uv sync --frozen --no-dev --no-install-project -q \
	  && uv pip install -q --python $(CURDIR)/.notices-venv/bin/python pip-licenses \
	  && $(CURDIR)/.notices-venv/bin/pip-licenses --format=markdown --with-urls --order=license \
	     --ignore-packages pip-licenses prettytable wcwidth tomli > $(CURDIR)/.notices-py.md
	cd frontend && npx -y license-checker@25.0.1 --production --json > $(CURDIR)/.notices-js.json
	python3 scripts/third_party_notices.py .notices-py.md .notices-js.json
	rm -rf .notices-venv .notices-py.md .notices-js.json

