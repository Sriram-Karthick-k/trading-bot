.PHONY: help dev dev-stop backend backend-https frontend stop test lint clean docker-up docker-down db-migrate

CERT_DIR   = certs
CERT_FILE  = $(CERT_DIR)/localhost.pem
CERT_KEY   = $(CERT_DIR)/localhost-key.pem

SSL_FLAGS  = --ssl-certfile $(CERT_FILE) --ssl-keyfile $(CERT_KEY)

BACKEND_PYTHON = backend/.venv/bin/python
BACKEND_UVICORN = backend/.venv/bin/uvicorn

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Development ──────────────────────────────────────────

dev: ## Start all services (HTTPS backend + frontend) in background
	-docker compose up -d postgres redis
	@echo "Starting backend on https://localhost:8000 ..."
	$(BACKEND_UVICORN) app.main:app --reload --port 8000 --app-dir backend $(SSL_FLAGS) & echo $$! > .pid.backend
	@echo "Starting frontend on https://localhost:3000 ..."
	cd frontend && npm run dev & echo $$! > .pid.frontend
	@echo ""
	@echo "  Backend : https://localhost:8000"
	@echo "  Frontend: https://localhost:3000"
	@echo "  Run 'make dev-stop' to stop both."
	@wait

dev-stop: ## Stop background dev servers started by 'make dev'
	@if [ -f .pid.backend ]; then \
		kill $$(cat .pid.backend) 2>/dev/null && echo "Backend stopped" || echo "Backend already stopped"; \
		rm -f .pid.backend; \
	fi
	@if [ -f .pid.frontend ]; then \
		kill $$(cat .pid.frontend) 2>/dev/null && echo "Frontend stopped" || echo "Frontend already stopped"; \
		rm -f .pid.frontend; \
	fi
	@# Also kill any orphaned uvicorn/next processes on the ports
	@pkill -f "[u]vicorn app.main:app" 2>/dev/null || true
	@pkill -f "[n]ext dev" 2>/dev/null || true
	@echo "Done."

stop: dev-stop ## Alias for dev-stop

backend: ## Start backend only (HTTPS on :8000)
	$(BACKEND_UVICORN) app.main:app --reload --port 8000 --app-dir backend $(SSL_FLAGS)

backend-http: ## Start backend only (plain HTTP on :8000, no SSL)
	$(BACKEND_UVICORN) app.main:app --reload --port 8000 --app-dir backend

frontend: ## Start frontend only (on :3000)
	cd frontend && npm run dev

# ── Docker ───────────────────────────────────────────────

docker-up: ## Start all with Docker Compose
	docker compose up -d --build

docker-down: ## Stop all containers
	docker compose down

docker-logs: ## View container logs
	docker compose logs -f

# ── Testing ──────────────────────────────────────────────

test: test-backend test-frontend ## Run all tests

test-backend: ## Run backend tests
	cd backend && .venv/bin/python -m pytest -v

test-unit: ## Run unit tests
	cd backend && .venv/bin/python -m pytest tests/unit -v

test-integration: ## Run integration tests
	cd backend && .venv/bin/python -m pytest tests/integration -v; s=$$?; [ $$s -eq 5 ] && echo "No integration tests yet" || exit $$s

test-api: ## Run API tests
	cd backend && .venv/bin/python -m pytest tests/api -v

test-cov: ## Run tests with coverage
	cd backend && .venv/bin/python -m pytest --cov=app --cov-report=html
	cd frontend && npm run test:coverage

test-frontend: ## Run frontend tests
	cd frontend && npm test

test-e2e: ## Run E2E tests
	cd frontend && npx playwright test

# ── Database ─────────────────────────────────────────────

db-migrate: ## Run database migrations
	cd backend && .venv/bin/python -m alembic upgrade head

db-revision: ## Create new migration
	cd backend && .venv/bin/python -m alembic revision --autogenerate -m "$(msg)"

# ── Utilities ────────────────────────────────────────────

lint: ## Lint all code
	cd backend && .venv/bin/python -m ruff check .
	cd frontend && npm run lint

clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/htmlcov frontend/.next frontend/node_modules/.cache

install-backend: ## Install backend dependencies
	cd backend && .venv/bin/pip install -r requirements-test.txt

install-frontend: ## Install frontend dependencies
	cd frontend && npm install
