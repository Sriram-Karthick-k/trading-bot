# Testing

The platform has comprehensive test coverage across both backend and frontend.

## Test Summary

| Suite | Framework | Tests | Coverage |
|-------|-----------|-------|----------|
| Backend | pytest | 103 | Unit + API |
| Frontend | Jest + Testing Library | 74 | Utils + API + Components + Hooks |
| **Total** | — | **177** | — |

## Running Tests

```bash
# All tests
make test

# Backend only
make test-backend

# Frontend only
make test-frontend

# Backend with coverage
make test-cov

# Specific backend test categories
make test-unit          # Unit tests
make test-api           # API route tests
make test-integration   # Integration tests

# Frontend with coverage
cd frontend && npm run test:coverage

# Frontend watch mode
cd frontend && npm run test:watch
```

---

## Backend Tests

Located in `backend/tests/`.

### Structure

```
backend/tests/
├── conftest.py              # Shared fixtures
├── unit/
│   ├── test_config_manager.py    # Config resolution tests
│   ├── test_risk_manager.py      # All 9 risk checks
│   ├── test_order_manager.py     # Signal processing pipeline
│   ├── test_mock_engine.py       # Mock order matching/fills
│   ├── test_mock_provider.py     # Provider interface compliance
│   ├── test_zerodha_mapper.py    # Type conversion tests
│   ├── test_provider_registry.py # Provider lifecycle
│   ├── test_strategy_base.py     # Strategy lifecycle/metrics
│   └── test_time_controller.py   # Virtual clock operations
└── api/
    ├── test_auth_routes.py       # Auth endpoint tests
    ├── test_order_routes.py      # Order CRUD tests
    ├── test_portfolio_routes.py  # Portfolio endpoints
    ├── test_market_routes.py     # Market data endpoints
    ├── test_strategy_routes.py   # Strategy management
    ├── test_mock_routes.py       # Mock session/time controls
    ├── test_provider_routes.py   # Provider lifecycle
    └── test_config_routes.py     # Config + risk endpoints
```

### Key Test Areas

**Config Manager** (unit)
- Three-layer resolution: DB > YAML > Env > Default
- Schema validation (type, min/max, enum)
- Change event audit trail

**Risk Manager** (unit)
- Kill switch blocks all orders
- Max order value check
- Max position value check
- Daily loss tracking and limit
- Open orders/positions limit
- Quantity per order limit
- Exchange whitelist
- Trading hours enforcement
- Order rate limiting

**Mock Engine** (unit)
- Market order immediate fill
- Limit order pending → trigger
- Slippage calculation
- Brokerage deduction
- Position creation and update
- Capital tracking
- Order cancellation

**Provider Registry** (unit)
- Registration and discovery
- Active provider switching
- Instance caching
- Missing provider handling

**Strategy Base** (unit)
- State machine transitions
- Parameter validation
- Signal emission and consumption
- Metrics tracking

**Time Controller** (unit)
- Market open/close advance
- Weekend skip (next trading day)
- Date range boundaries
- Pause/resume
- Speed multiplier
- Progress calculation

### Running Specific Tests

```bash
# Single test file
cd backend && .venv/bin/python -m pytest tests/unit/test_risk_manager.py -v

# Single test case
cd backend && .venv/bin/python -m pytest tests/unit/test_risk_manager.py::TestRiskManager::test_kill_switch -v

# With print output
cd backend && .venv/bin/python -m pytest -s

# Stop on first failure
cd backend && .venv/bin/python -m pytest -x
```

---

## Frontend Tests

Located in `frontend/src/__tests__/`.

### Configuration

- **jest.config.js**: ts-jest transform, jsdom environment, module path aliases, CSS mocking
- **jest.setup.ts**: jest-dom matchers, next/navigation mocks, environment variables

### Test Files

#### `utils.test.ts` — Utility Functions (15 tests)
- `cn()`: class merging, conditional classes, Tailwind deduplication
- `formatCurrency()`: INR format, negative values, decimals, zero
- `formatPnl()`: positive/negative prefix
- `formatNumber()`: decimal precision
- `formatPercent()`: sign prefix

#### `api.test.ts` — API Client (30 tests)
- Mocks `global.fetch`
- Tests every API namespace: health, auth, orders, portfolio, strategies, providers, config, mock, market
- Verifies correct URLs, HTTP methods, and request bodies
- Error handling: `ApiError` on non-ok responses

#### `components.test.tsx` — UI Components (29 tests)
- Card: renders children, noPadding, custom className
- Button: variants (primary/danger/outline), sizes (sm/md/lg), disabled state
- Badge: variant colors, StatusBadge mapping
- Input: with/without label
- Select: renders options
- MetricCard: title, value, subtitle
- ProgressBar: label, aria role, value clamping
- PageHeader: title, subtitle, action slot
- EmptyState: title, description, icon

#### `hooks.test.ts` — Custom Hooks (5 tests)
- WebSocket connection
- Disabled state (no connection)
- Subscribe message on connect
- onTick callback
- Manual subscribe/unsubscribe methods

### Running Frontend Tests

```bash
cd frontend

# Run all
npm test

# Watch mode
npm run test:watch

# Coverage report
npm run test:coverage

# Verbose output
npx jest --verbose

# Single file
npx jest src/__tests__/api.test.ts

# Pattern match
npx jest --testPathPattern="components"
```

---

## Writing New Tests

### Backend Test Template

```python
import pytest
from unittest.mock import MagicMock, AsyncMock

class TestMyFeature:
    def setup_method(self):
        """Runs before each test"""
        self.mock_provider = MagicMock()
        self.feature = MyFeature(provider=self.mock_provider)

    def test_basic_functionality(self):
        result = self.feature.do_something("input")
        assert result == expected_output

    def test_edge_case(self):
        with pytest.raises(ValueError, match="Invalid input"):
            self.feature.do_something(None)

    @pytest.mark.asyncio
    async def test_async_operation(self):
        self.mock_provider.fetch = AsyncMock(return_value={"data": 1})
        result = await self.feature.fetch_data()
        assert result["data"] == 1
```

### Frontend Test Template

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { MyComponent } from "@/components/MyComponent";

describe("MyComponent", () => {
  it("renders correctly", () => {
    render(<MyComponent title="Test" />);
    expect(screen.getByText("Test")).toBeInTheDocument();
  });

  it("handles click", () => {
    const onClick = jest.fn();
    render(<MyComponent onClick={onClick} />);
    fireEvent.click(screen.getByRole("button"));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
```

## CI Pipeline

```bash
# Full validation pipeline
make lint           # Lint all code
make test           # Run all tests
make test-cov       # Coverage report
```
