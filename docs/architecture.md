# Architecture

## System Overview

The Zerodha Trade Platform is a full-stack automated trading system with a Python FastAPI backend and a Next.js TypeScript frontend. It uses a provider abstraction to support both live trading (Zerodha Kite Connect) and paper trading (Mock engine) through a unified interface.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                       │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │Dashboard│ │  Orders  │ │Portfolio │ │Strategies│  ...       │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       └───────────┴────────────┴─────────────┘                 │
│                          │                                      │
│              ┌───────────┴───────────┐                         │
│              │  API Client (fetch)   │  WebSocket (ticks)      │
│              └───────────┬───────────┘                         │
└──────────────────────────┼─────────────────────────────────────┘
                           │  HTTP /api/*  (proxied via Next.js)
┌──────────────────────────┼─────────────────────────────────────┐
│                    Backend (FastAPI)                            │
│              ┌───────────┴───────────┐                         │
│              │     API Routes        │                         │
│              │  auth│orders│market   │                         │
│              │ portfolio│strategies  │                         │
│              │  mock│providers│config │                         │
│              └───────────┬───────────┘                         │
│                          │                                      │
│    ┌─────────────────────┼─────────────────────────┐           │
│    │              Dependency Injection              │           │
│    │  ConfigManager · RiskManager · OrderManager   │           │
│    │  Clock · Provider · Strategies                │           │
│    └──────────┬──────────┬──────────┬──────────────┘           │
│               │          │          │                           │
│  ┌────────────┴──┐  ┌───┴───┐  ┌──┴──────────────┐           │
│  │ ConfigManager │  │ Risk  │  │  OrderManager    │           │
│  │ DB>YAML>Env>  │  │Manager│  │ Signals→Orders   │           │
│  │ Defaults      │  │ 9chks │  │                  │           │
│  └───────────────┘  └───────┘  └──────────────────┘           │
│                          │                                      │
│    ┌─────────────────────┼─────────────────────────┐           │
│    │          Provider Registry                     │           │
│    │  ┌─────────────┐  ┌─────────────┐             │           │
│    │  │  Zerodha     │  │    Mock     │             │           │
│    │  │  Provider    │  │  Provider   │             │           │
│    │  │ (Kite API)   │  │ (In-memory) │             │           │
│    │  └─────────────┘  └─────────────┘             │           │
│    └───────────────────────────────────────────────┘           │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────────┐          │
│  │PostgreSQL│  │  Redis   │  │  Strategy Framework  │          │
│  │  (ORM)   │  │ (cache)  │  │  Tick→Signal→Order   │          │
│  └──────────┘  └──────────┘  └─────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

## Design Patterns

### 1. Provider Abstraction

All broker interactions go through an abstract `BrokerProvider` base class. This ensures:
- **Swappability**: Switch between live (Zerodha) and paper (Mock) trading at runtime
- **Testability**: Mock provider for tests without real API calls
- **Extensibility**: Add new brokers by implementing the interface

```python
class BrokerProvider(ABC):
    @abstractmethod
    async def place_order(self, request: OrderRequest) -> str: ...
    @abstractmethod
    async def get_positions(self) -> PositionsData: ...
    @abstractmethod
    async def get_quote(self, instruments: list[str]) -> dict: ...
    # ... 20+ abstract methods
```

The **Provider Registry** manages lifecycle: discovery, instantiation, caching, and active provider selection.

### 2. Three-Layer Configuration

Configuration resolves through four layers (highest priority first):

| Layer | Source | Use Case |
|-------|--------|----------|
| 1. DB Override | Runtime UI changes | Kill switch, risk limit adjustments |
| 2. YAML Files | `config/*.yaml` | Version-controlled defaults |
| 3. Environment | `TRADE_*` env vars | Deployment customization |
| 4. Schema Default | Hardcoded in code | Absolute fallback |

Each config key has a registered schema with type, min/max, and allowed values.

### 3. Signal-Based Trading Pipeline

Strategies don't place orders directly. Instead:

```
Market Data (Tick/Candle)
    │
    ▼
Strategy.on_tick() / on_candle()
    │
    ▼
StrategySignal { instrument, action, confidence, reason }
    │
    ▼
OrderManager.process_signals()
    │
    ▼
RiskManager.check_order()  ──rejected──▶ Log & Skip
    │ passed
    ▼
Provider.place_order()
    │
    ▼
Order Confirmation / Fill Update
```

This decoupling ensures:
- Risk checks are **always** enforced
- Strategies are **pure** signal generators
- Order lifecycle is **centrally** managed

### 4. Clock Abstraction

All time-dependent code uses a `Clock` protocol instead of `datetime.now()`:

| Clock Type | Usage |
|------------|-------|
| `RealClock` | Production — returns actual IST time |
| `VirtualClock` | Testing — supports `set_time()`, `advance()`, `set_speed()`, `pause()` |

This enables deterministic tests, fast-forward simulation, and replay without changing business logic.

### 5. Dependency Injection

FastAPI's `Depends()` system provides singleton services to route handlers:

```python
# All routes receive these via type annotations
ConfigDep  = Annotated[ConfigManager, Depends(get_config_manager)]
ProviderDep = Annotated[BrokerProvider, Depends(get_provider)]
RiskDep    = Annotated[RiskManager,    Depends(get_risk_manager)]
OrderDep   = Annotated[OrderManager,   Depends(get_order_manager)]
ClockDep   = Annotated[Clock,          Depends(get_clock)]
```

## Data Flow

### Order Placement Flow

```
Frontend                  Backend
────────                  ───────
PlaceOrderForm
  │
  ├─POST /api/orders/place──────▶  orders.py route
  │                                   │
  │                                   ├─▶ RiskManager.check_order()
  │                                   │     ├─ kill switch check
  │                                   │     ├─ max order value
  │                                   │     ├─ max position value
  │                                   │     ├─ daily loss limit
  │                                   │     ├─ open orders limit
  │                                   │     ├─ quantity limit
  │                                   │     ├─ exchange allowed
  │                                   │     ├─ trading hours
  │                                   │     └─ order rate limit
  │                                   │
  │                                   ├─▶ Provider.place_order()
  │                                   │     ├─ Zerodha: Kite API call
  │                                   │     └─ Mock: Engine simulation
  │                                   │
  │  ◀───── { order_id } ────────────┘
  │
Orders Page (SWR polls /orders every 3s)
```

### Real-Time Tick Flow

```
Provider Ticker (WebSocket)
  │
  ├──tick──▶ Strategy.on_tick()
  │              │
  │              └──signal──▶ OrderManager
  │
  ├──tick──▶ Frontend WebSocket (/ws/ticks/{clientId})
  │              │
  │              └──▶ useTickStream hook ──▶ UI update
  │
  └──tick──▶ MockEngine._check_pending_orders()
                 │
                 └──fill──▶ Position update
```

## Technology Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend Framework | FastAPI | 0.115.12 |
| Python Runtime | Python | 3.14.3 |
| ORM | SQLAlchemy (async) | 2.0.41 |
| Validation | Pydantic | 2.11.7 |
| Database | PostgreSQL | 16 |
| Cache | Redis | 7 |
| Broker SDK | kiteconnect | 5.0.1 |
| Frontend Framework | Next.js | 14.2.29 |
| UI Library | React | 18.3.1 |
| Type System | TypeScript | 5.8.3 |
| Styling | Tailwind CSS | 3.4.17 |
| Data Fetching | SWR | 2.3.3 |
| State Management | Zustand | 5.0.5 |
| Charts | Recharts | 2.15.3 |
| Backend Tests | pytest | 9.0.2 |
| Frontend Tests | Jest + Testing Library | 29.7 |
| Containerization | Docker Compose | — |
