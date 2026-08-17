.DEFAULT_GOAL := help
COMPOSE := docker compose -f infra/docker-compose.yml

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: clean-cache
clean-cache: ## Remove project-local Python and tool cache files
	@find . -path './.git' -prune -o -path './.venv' -prune -o -type d \( \
		-name '__pycache__' -o \
		-name '.pytest_cache' -o \
		-name '.mypy_cache' -o \
		-name '.ruff_cache' -o \
		-name '.import_linter_cache' -o \
		-name '.cache' \
	\) -prune -exec rm -rf -- {} +
	@find . -path './.git' -prune -o -path './.venv' -prune -o -type f \( \
		-name '*.pyc' -o \
		-name '*.pyo' \
	\) -exec rm -f -- {} +

.PHONY: install
install: ## Sync dependencies with uv
	uv sync --all-extras --dev

.PHONY: dev docker-up
dev docker-up: ## Bring up Postgres+pgvector, Redis, Langfuse and the API
	$(COMPOSE) up -d

.PHONY: docker-down
docker-down: ## Stop the dev stack
	$(COMPOSE) down

.PHONY: docker-down-v
docker-down-v: ## Stop the dev stack and delete volumes (destroys data)
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail the dev stack logs
	$(COMPOSE) logs -f

.PHONY: api
api: ## Run the API locally with reload
	uv run uvicorn apps.api.main:app --reload

.PHONY: worker
worker: ## Run the background worker
	uv run python -m apps.worker.main

.PHONY: migrate
migrate: ## Apply database migrations
	uv run alembic upgrade head

.PHONY: revision
revision: ## Autogenerate a migration: make revision m="add chunks"
	uv run alembic revision --autogenerate -m "$(m)"

.PHONY: ingest
ingest: ## Ingest the corpus (idempotent)
	uv run python scripts/ingest.py

.PHONY: eval
eval: ## Run the golden set and write a report to evals/reports/
	uv run python scripts/run_eval.py

.PHONY: lint
lint: ## ruff check + format check
	uv run ruff check .
	uv run ruff format --check .

.PHONY: fmt
fmt: ## Apply ruff formatting and fixes
	uv run ruff check --fix .
	uv run ruff format .

.PHONY: typecheck
typecheck: ## mypy
	uv run mypy src apps evals scripts

.PHONY: arch
arch: ## Enforce module boundaries
	uv run lint-imports

.PHONY: test
test: ## Run the test suite
	uv run pytest

.PHONY: check
check: lint typecheck arch test ## Everything CI runs (minus the eval gate)

.PHONY: deploy
deploy: ## Deploy to the VPS (see .github/workflows/deploy.yml)
	bash scripts/deploy.sh
