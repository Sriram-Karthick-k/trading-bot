---
description: Zerodha Trade Platform development workflow agent
applyTo: "**"
---

# Zerodha Trade Platform — Agent Workflow

## Project Context

Multi-provider automated trading platform with FastAPI backend and Next.js frontend.
- **Backend**: Python 3.14, FastAPI, SQLAlchemy, pytest (103 tests)
- **Frontend**: Next.js 14, React 18, TypeScript, Jest (74 tests)
- **Database**: PostgreSQL 16, Redis 7
- **Infra**: Docker Compose, Makefile

## Directory Structure

```
backend/app/           → FastAPI application
backend/app/api/       → API route handlers
backend/app/core/      → Config, Risk, Order managers
backend/app/providers/  → Broker providers (zerodha, mock)
backend/app/strategies/ → Strategy framework
backend/app/models/    → SQLAlchemy ORM models
backend/config/        → YAML configuration files
backend/tests/         → pytest test suite
frontend/src/app/      → Next.js pages
frontend/src/components/ → Reusable UI components
frontend/src/hooks/    → React hooks (useData, useTickStream)
frontend/src/lib/      → API client and utilities
frontend/src/__tests__/ → Jest test suite
docs/                  → Project documentation
```

## Development Checklists

### Before Starting Any Feature

- [ ] Read relevant existing code (provider, route, component)
- [ ] Check `docs/` for architecture context
- [ ] Identify which tests need to be written
- [ ] Verify current tests pass: `make test`

### After Completing Any Feature

- [ ] All existing tests still pass: `make test`
- [ ] New tests written for the feature
- [ ] No TypeScript errors: `cd frontend && npx tsc --noEmit`
- [ ] Backend lints clean: `cd backend && .venv/bin/python -m ruff check .`
- [ ] Frontend lints clean: `cd frontend && npm run lint`
- [ ] Documentation updated in `docs/` if needed

---

## Workflow: Write Test Cases

### Backend Tests

1. Identify the module to test (e.g., `backend/app/core/risk_manager.py`)
2. Create test file: `backend/tests/unit/test_<module>.py` or `backend/tests/api/test_<route>.py`
3. Use fixtures from `backend/tests/conftest.py`
4. Test patterns:
   - Unit tests mock dependencies (`MagicMock`, `AsyncMock`)
   - API tests use FastAPI `TestClient`
   - Cover happy path, edge cases, and error conditions
5. Run: `cd backend && .venv/bin/python -m pytest tests/unit/test_<module>.py -v`
6. Verify: `make test-backend` (all 103+ tests pass)

### Frontend Tests

1. Identify what to test (component, hook, utility, API call)
2. Create test file in `frontend/src/__tests__/`
3. Test patterns:
   - **Components**: `@testing-library/react` — render, query, assert
   - **Hooks**: `renderHook` + `act` from Testing Library
   - **API client**: Mock `global.fetch`, verify URLs and methods
   - **Utilities**: Direct function calls with assertions
4. Run: `cd frontend && npx jest src/__tests__/<file>.test.ts -v`
5. Verify: `make test-frontend` (all 74+ tests pass)

### Test Naming Convention

```
Backend:  tests/unit/test_<module>.py       → TestClassName::test_description
          tests/api/test_<route>_routes.py  → TestClassName::test_endpoint_purpose
Frontend: src/__tests__/<area>.test.ts      → describe("area") > it("does thing")
```

---

## Workflow: Run Unit Tests

```bash
# All tests (backend + frontend)
make test

# Backend only (103 tests)
make test-backend

# Frontend only (74 tests)
make test-frontend

# With coverage
make test-cov

# Targeted backend tests
make test-unit            # Unit tests only
make test-api             # API tests only

# Single backend test file
cd backend && .venv/bin/python -m pytest tests/unit/test_risk_manager.py -v

# Single frontend test file
cd frontend && npx jest src/__tests__/components.test.tsx --verbose

# Watch mode (frontend)
cd frontend && npm run test:watch
```

---

## Workflow: Add a New API Endpoint

1. **Define route** in `backend/app/api/routes/<module>.py`
2. **Use dependency injection**: `ConfigDep`, `ProviderDep`, `RiskDep`, etc.
3. **Add Pydantic models** for request/response bodies
4. **Register route** in `backend/app/main.py` if new module
5. **Write API test** in `backend/tests/api/test_<module>_routes.py`
6. **Add frontend API method** in `frontend/src/lib/api.ts`
7. **Add TypeScript types** in `frontend/src/types/index.ts` if needed
8. **Write API client test** in `frontend/src/__tests__/api.test.ts`
9. **Update docs** in `docs/api-reference.md`
10. Run `make test` to verify

---

## Workflow: Add a New Provider

1. Create directory: `backend/app/providers/<name>/`
2. Implement `BrokerProvider` abstract class in `provider.py`
3. Create mapper class for type conversion
4. Register in `backend/app/providers/registry.py` → `discover_providers()`
5. Add config: `backend/config/providers/<name>.yaml`
6. Write unit tests: `backend/tests/unit/test_<name>_provider.py`
7. Write mapper tests: `backend/tests/unit/test_<name>_mapper.py`
8. Update `docs/providers.md`
9. Run `make test`

---

## Workflow: Add a New Strategy

1. Create file: `backend/app/strategies/<name>.py`
2. Subclass `Strategy` from `backend/app/strategies/base.py`
3. Implement: `name()`, `description()`, `get_params_schema()`, `get_instruments()`, `on_tick()`, `on_candle()`
4. Write tests: `backend/tests/unit/test_<name>_strategy.py`
5. Update `docs/strategies.md`
6. Run `make test`

---

## Workflow: Add a New Frontend Page

1. Create `frontend/src/app/<name>/page.tsx`
2. Extract reusable parts into `frontend/src/components/<domain>/`
3. Add SWR hook in `frontend/src/hooks/useData.ts` if needed
4. Add API methods in `frontend/src/lib/api.ts` if needed
5. Add TypeScript types in `frontend/src/types/index.ts`
6. Add navigation link in sidebar (`frontend/src/components/ui/Sidebar.tsx`)
7. Write component tests in `frontend/src/__tests__/`
8. Verify: `make test-frontend`

---

## Workflow: Add a New UI Component

1. Create in `frontend/src/components/ui/<Name>.tsx`
2. Use `forwardRef` for HTML element wrappers
3. Use CVA (`cva`) for variant-based styling
4. Use `cn()` from `@/lib/utils` for class merging
5. Export from `frontend/src/components/ui/index.ts`
6. Write tests in `frontend/src/__tests__/components.test.tsx`
7. Run `make test-frontend`

---

## Workflow: Modify Risk Limits

1. Update schema in `backend/app/core/config_manager.py` → `_SCHEMA_REGISTRY`
2. Update `RiskLimits` dataclass in `backend/app/core/risk_manager.py`
3. Add risk check method if new check type
4. Update `config/risk.yaml` with new defaults
5. Update risk limit tests in `backend/tests/unit/test_risk_manager.py`
6. Update frontend types in `frontend/src/types/index.ts`
7. Update Settings page if UI control needed
8. Update `docs/risk-management.md` and `docs/configuration.md`
9. Run `make test`

---

## Workflow: Debug a Failing Test

1. Run the specific failing test with verbose output:
   - Backend: `cd backend && .venv/bin/python -m pytest tests/path/test_file.py::TestClass::test_name -v -s`
   - Frontend: `cd frontend && npx jest src/__tests__/file.test.ts --verbose`
2. Check the error message and traceback
3. Read the test and the source code it tests
4. Check if it's a mock setup issue (wrong return value, missing mock)
5. Fix the source code or the test
6. Re-run the specific test
7. Run full suite: `make test`

---

## Code Quality Rules

- **Zero tolerance for test failures** — all 177 tests must pass
- **Backend uses venv** — always use `.venv/bin/python` or `.venv/bin/pip`
- **Frontend uses npm** — run commands from `frontend/` directory
- **Type safety** — TypeScript strict mode, Pydantic validation
- **No hardcoded URLs** — use config/env vars
- **Risk checks always on** — never bypass RiskManager
- **Provider-agnostic** — business logic never references Kite/Zerodha directly

## Key Commands Reference

| Command | Purpose |
|---------|---------|
| `make test` | Run all 177 tests |
| `make test-backend` | Run 103 backend tests |
| `make test-frontend` | Run 74 frontend tests |
| `make dev` | Start full dev environment |
| `make lint` | Lint all code |
| `make clean` | Remove build artifacts |
| `make docker-up` | Full Docker deployment |
| `make help` | Show all commands |
