.PHONY: help up down build migrate seed lint test type-check install \
        up-llm up-langfuse vault-init logs ps clean

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Docker Compose ────────────────────────────────────────────────────────────
up: ## Start core services (web, api, worker, postgres, redis, vault)
	@cp -n .env.example .env 2>/dev/null && echo "Created .env from .env.example — fill in secrets!" || true
	docker compose up --build -d
	@echo ""
	@echo "  $(BOLD)web$(RESET)    → http://localhost:3000"
	@echo "  $(BOLD)api$(RESET)    → http://localhost:8000/docs"
	@echo "  $(BOLD)vault$(RESET)  → http://localhost:8200"

up-llm: ## Start core + Ollama (LLM profile)
	docker compose --profile llm up --build -d

up-langfuse: ## Start core + Langfuse (tracing profile)
	docker compose --profile langfuse up --build -d

down: ## Stop all services
	docker compose --profile llm --profile langfuse down

build: ## Build all Docker images
	docker compose --profile llm --profile langfuse build

ps: ## Show running services
	docker compose ps

logs: ## Tail logs (optionally: make logs s=api)
	docker compose logs -f $(s)

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Run Alembic migrations (upgrade head)
	docker compose exec api uv run alembic upgrade head

migrate-new: ## Create a new migration: make migrate-new m="describe change"
	docker compose exec api uv run alembic revision --autogenerate -m "$(m)"

seed: ## Seed demo data (M3+)
	docker compose exec worker uv run python -m worker.jobs.seed

# ── Vault ─────────────────────────────────────────────────────────────────────
vault-init: ## Run Vault bootstrap (AppRole setup)
	docker compose exec vault sh /vault/init.sh

# ── Python ────────────────────────────────────────────────────────────────────
install: ## Install all Python deps via uv
	uv sync --all-packages

lint: ## Run ruff + mypy
	uv run ruff check api/ worker/ shared/
	uv run mypy api/ worker/ shared/

fmt: ## Auto-fix formatting with ruff
	uv run ruff check --fix api/ worker/ shared/
	uv run ruff format api/ worker/ shared/

test: ## Run Python tests
	uv run pytest -v

# ── Web (pnpm) ────────────────────────────────────────────────────────────────
web-install: ## Install web deps
	cd web && pnpm install

web-dev: ## Start Next.js dev server
	cd web && pnpm dev

web-lint: ## Lint web
	cd web && pnpm lint

web-type-check: ## Type-check web
	cd web && pnpm type-check

# ── Clean ─────────────────────────────────────────────────────────────────────
clean: ## Remove volumes + built images
	docker compose --profile llm --profile langfuse down -v --remove-orphans
	docker compose rm -f
