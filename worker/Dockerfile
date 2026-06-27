FROM python:3.12-alpine AS base

WORKDIR /app

# Build dependencies for C extensions (asyncpg, cryptography, boto3, etc.)
RUN apk add --no-cache gcc musl-dev libffi-dev openssl-dev

# Install uv
RUN pip install --quiet --no-cache-dir uv

COPY pyproject.toml ./
COPY shared/pyproject.toml shared/
COPY worker/pyproject.toml worker/

COPY shared/ shared/
COPY worker/ worker/

# Install worker + shared dependencies (no dev extras)
RUN uv sync --package sprawl-worker --no-dev

CMD ["uv", "run", "arq", "worker.main.WorkerSettings"]
