.PHONY: help up down build migrate migrate-new seed lint fmt test \
        up-llm up-langfuse vault-init logs ps clean web-install web-dev web-lint web-type-check

# ── Colors ────────────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m

# ── Docker Compose — auto-detect plugin (docker compose) vs standalone ─────────
# Uses the Homebrew `docker-compose` when the Docker CLI plugin is absent.
COMPOSE := $(shell \
	if docker compose version > /dev/null 2>&1; then \
		echo "docker compose"; \
	elif command -v docker-compose > /dev/null 2>&1; then \
		echo "docker-compose"; \
	else \
		echo "docker compose"; \
	fi)

help: ## Show this help
	@echo "  compose: $(COMPOSE)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-18s$(RESET) %s\n", $$1, $$2}'
	@echo ""

# ── Core services ─────────────────────────────────────────────────────────────
up: ## Start backend services (api, worker, postgres, redis, vault). For web: make web-dev
	@cp -n .env.example .env 2>/dev/null && echo "Created .env from .env.example — fill in secrets!" || true
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  $(BOLD)api$(RESET)    → http://localhost:8000/docs"
	@echo "  $(BOLD)vault$(RESET)  → http://localhost:8200"
	@echo "  $(BOLD)web$(RESET)    → run 'make web-dev' in a separate terminal (http://localhost:3000)"

up-llm: ## Start core + Ollama (LLM profile)
	$(COMPOSE) --profile llm up --build -d

up-langfuse: ## Start core + Langfuse (tracing profile)
	$(COMPOSE) --profile langfuse up --build -d

down: ## Stop all services
	$(COMPOSE) --profile llm --profile langfuse down

build: ## Rebuild all Docker images without cache
	$(COMPOSE) --profile llm --profile langfuse build

ps: ## Show running services
	$(COMPOSE) ps

logs: ## Tail logs (optionally: make logs s=api)
	$(COMPOSE) logs -f $(s)

# ── Database ──────────────────────────────────────────────────────────────────
migrate: ## Run Alembic migrations (upgrade head)
	$(COMPOSE) exec api uv run alembic upgrade head

migrate-new: ## Create a new migration: make migrate-new m="describe change"
	$(COMPOSE) exec api uv run alembic revision --autogenerate -m "$(m)"

seed: ## Seed demo data (M3+)
	$(COMPOSE) exec worker uv run python -m worker.jobs.seed

# ── Vault ─────────────────────────────────────────────────────────────────────
vault-init: ## Run Vault AppRole bootstrap script
	$(COMPOSE) exec vault sh /vault/init.sh

# ── Python (uv) ───────────────────────────────────────────────────────────────
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

web-dev: ## Start Next.js dev server (no Docker)
	cd web && pnpm dev

web-lint: ## Lint web
	cd web && pnpm lint

web-type-check: ## Type-check web
	cd web && pnpm type-check

# ── Clean ─────────────────────────────────────────────────────────────────────
clean: ## Remove volumes + built images
	$(COMPOSE) --profile llm --profile langfuse down -v --remove-orphans
