# Контекст сборки — корень репозитория (docs/13-deploy-demo.md §3.1)
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
COPY eval/reports/ /app/eval/reports/
RUN useradd -m -u 10001 app && mkdir -p /app/data/runtime /app/data/raw && chown -R app /app/data/runtime
COPY --chmod=755 backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENV PATH="/app/backend/.venv/bin:$PATH" DATA_DIR=/app/data CONFIG_DIR=/app/config
EXPOSE 8000
# Стартует от root только ради chown тома, процесс работает от app
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "alfa_insight.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
