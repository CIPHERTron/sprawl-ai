FROM python:3.12-slim AS base

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy workspace manifests first (cache layer)
COPY pyproject.toml ./
COPY shared/pyproject.toml shared/
COPY api/pyproject.toml api/

# Copy source
COPY shared/ shared/
COPY api/ api/

# Install api + shared dependencies (no dev extras)
RUN uv sync --package sprawl-api --no-dev --frozen 2>/dev/null || \
    uv sync --package sprawl-api --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
