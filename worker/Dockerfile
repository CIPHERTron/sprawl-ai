FROM python:3.12-slim AS base

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

COPY pyproject.toml ./
COPY shared/pyproject.toml shared/
COPY worker/pyproject.toml worker/

COPY shared/ shared/
COPY worker/ worker/

RUN uv sync --package sprawl-worker --no-dev --frozen 2>/dev/null || \
    uv sync --package sprawl-worker --no-dev

CMD ["uv", "run", "arq", "worker.main.WorkerSettings"]
