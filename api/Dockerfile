FROM python:3.12-alpine AS base

WORKDIR /app

# Build dependencies for C extensions (asyncpg, cryptography, etc.)
RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev

# Install uv
RUN pip install --quiet --no-cache-dir uv

# Copy workspace manifests first (layer cache — rebuilt only on dependency changes)
COPY pyproject.toml ./
COPY shared/pyproject.toml shared/
COPY api/pyproject.toml api/

# Copy source
COPY shared/ shared/
COPY api/ api/

# Install api + shared dependencies (no dev extras)
RUN uv sync --package sprawl-api --no-dev

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
