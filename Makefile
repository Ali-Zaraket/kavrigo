# Kavrigo developer entry points.
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV := .venv
PY := $(VENV)/bin/python
COMPOSE := docker compose -f kavrigo-infra/local/docker-compose.yml
PKGS := kavrigo-engine/libs/domain kavrigo-platform/services/api kavrigo-engine/services/engine-worker
SRC := kavrigo-engine/libs/domain/src kavrigo-platform/services/api/src kavrigo-engine/services/engine-worker/src

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: setup
setup: ## Create the virtualenv and install workspace packages
	@if command -v uv >/dev/null 2>&1; then \
	  echo "==> uv"; uv sync --all-packages; \
	else \
	  echo "==> uv not found; falling back to venv + pip (install uv: https://docs.astral.sh/uv/)"; \
	  python3 -m venv $(VENV); \
	  $(PY) -m pip install --quiet --upgrade pip; \
	  $(PY) -m pip install --quiet pytest pytest-asyncio pytest-cov hypothesis httpx httpx2 ruff mypy pre-commit; \
	  $(PY) -m pip install --quiet $(foreach p,$(PKGS),-e $(p)); \
	fi
	@echo "==> ready. 'make test' to verify."

.PHONY: test
test: ## Run unit and property tests (no docker stack required)
	$(PY) -m pytest

.PHONY: cov
cov: ## Run tests with coverage
	$(PY) -m pytest --cov=kavrigo_domain --cov=kavrigo_api --cov-report=term-missing

.PHONY: lint
lint: ## Lint and check formatting
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

.PHONY: fmt
fmt: ## Auto-fix lint findings and format
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

.PHONY: typecheck
typecheck: ## Strict type check
	$(PY) -m mypy $(SRC)

.PHONY: check
check: lint typecheck test ## Everything CI runs on a pull request

.PHONY: up
up: ## Start the local stack
	$(COMPOSE) up -d --build
	@echo "==> API      http://localhost:58000/docs"
	@echo "==> Temporal http://localhost:58233"

.PHONY: down
down: ## Stop the local stack
	$(COMPOSE) down

.PHONY: clean-volumes
clean-volumes: ## Stop the stack and delete its data volumes
	$(COMPOSE) down -v

.PHONY: logs
logs: ## Tail stack logs
	$(COMPOSE) logs -f --tail=100

.PHONY: ps
ps: ## Show stack status
	$(COMPOSE) ps

.PHONY: compose-validate
compose-validate: ## Validate the compose file without pulling images
	$(COMPOSE) config -q && echo "compose OK"

.PHONY: migrate
migrate: ## Apply database migrations (runs as the owning role)
	cd kavrigo-platform/services/api && \
	  POSTGRES_MIGRATION_DSN=$${POSTGRES_MIGRATION_DSN:-postgresql+asyncpg://kavrigo:kavrigo_local_dev@localhost:55432/kavrigo} \
	  ../../../$(PY) -m alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back the most recent migration
	cd kavrigo-platform/services/api && \
	  POSTGRES_MIGRATION_DSN=$${POSTGRES_MIGRATION_DSN:-postgresql+asyncpg://kavrigo:kavrigo_local_dev@localhost:55432/kavrigo} \
	  ../../../$(PY) -m alembic downgrade -1

.PHONY: test-integration
test-integration: ## Run integration tests against the local stack (requires `make up` + `make migrate`)
	$(PY) -m pytest -m integration

.PHONY: proto
proto: ## Generate Python bindings from the Protobuf contracts
	@command -v protoc >/dev/null 2>&1 || { echo "protoc not found; install protobuf"; exit 1; }
	@mkdir -p kavrigo-engine/libs/data-contracts/_generated
	protoc -I kavrigo-engine/libs/data-contracts/proto \
	  --python_out=kavrigo-engine/libs/data-contracts/_generated \
	  --pyi_out=kavrigo-engine/libs/data-contracts/_generated \
	  $$(find kavrigo-engine/libs/data-contracts/proto -name '*.proto')
	@echo "==> generated into kavrigo-engine/libs/data-contracts/_generated (git-ignored)"

.PHONY: hooks
hooks: ## Install pre-commit hooks
	$(PY) -m pre_commit install

.PHONY: secrets-scan
secrets-scan: ## Scan the working tree for secrets
	@command -v gitleaks >/dev/null 2>&1 || { echo "gitleaks not found; brew install gitleaks"; exit 1; }
	gitleaks detect --config .gitleaks.toml --no-banner --redact
