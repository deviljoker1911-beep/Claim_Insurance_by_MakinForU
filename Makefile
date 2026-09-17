# ClaimAI — developer commands. Run `make help` for the list.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_HOST ?= 127.0.0.1
BACKEND_PORT ?= 8010
# Pause between processing stages during the demo, so the timeline is readable.
DEMO_PACING_MS ?= 120
PYTHON ?= 3.12

.PHONY: help setup env install install-backend install-frontend db db-docker \
        dev backend frontend build demo test test-backend lint clean \
        demo-data demo-check reset smoke

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: env install db ## First-time setup: .env, dependencies, database

env: ## Create .env from .env.example (keeps an existing .env)
	@if [ -f .env ]; then echo ".env already exists"; else cp .env.example .env && echo "Created .env from .env.example"; fi

install: install-backend install-frontend ## Install backend and frontend dependencies

install-backend:
	cd backend && uv sync --python $(PYTHON)

install-frontend:
	cd frontend && npm install

db: ## Create the PostgreSQL database named in DATABASE_URL (if missing)
	cd backend && uv run python scripts/ensure_db.py

db-docker: ## Start PostgreSQL 16 in Docker on port 5433
	docker compose up -d db

dev: ## Run API (:8010) and web app (:5173) together
	@trap 'kill 0' EXIT INT TERM; \
	$(MAKE) --no-print-directory backend & \
	$(MAKE) --no-print-directory frontend & \
	wait

backend: ## Run the API on http://127.0.0.1:8010
	cd backend && uv run uvicorn app.main:app --host $(BACKEND_HOST) --port $(BACKEND_PORT)

frontend: ## Run the web app on http://127.0.0.1:5173
	cd frontend && npm run dev

build: ## Production build of the web app (type-check + bundle)
	cd frontend && npm run build

demo: build ## Single-port demo: API + built web app on http://127.0.0.1:8010
	cd backend && SERVE_FRONTEND=true DEMO_PACING_MS=$(DEMO_PACING_MS) \
		uv run uvicorn app.main:app --host $(BACKEND_HOST) --port $(BACKEND_PORT)

test: test-backend lint build ## Backend tests, frontend lint and production build

test-backend: ## Backend tests (isolated temporary SQLite database)
	cd backend && uv run pytest

lint: ## Lint the frontend
	cd frontend && npm run lint

demo-data: ## Regenerate the synthetic demo documents in demo_data/ (deterministic)
	cd backend && RL_invariant=1 uv run python -m app.demo_gen

demo-check: ## Verify demo_data/ matches the generator byte for byte
	cd backend && RL_invariant=1 uv run python -m app.demo_gen --check

reset: ## Reset the demo workspace through the running API (next claim: CLM-2026-00123)
	curl -fsS -X POST -H 'Content-Type: application/json' -d '{"confirm": true}' \
		http://$(BACKEND_HOST):$(BACKEND_PORT)/api/demo/reset | python3 -m json.tool

smoke: ## End-to-end smoke test against the running API and its database (resets the workspace)
	cd backend && uv run python scripts/smoke_test.py --reset --base-url http://$(BACKEND_HOST):$(BACKEND_PORT)

clean: ## Remove build output and caches
	rm -rf frontend/dist backend/.pytest_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
