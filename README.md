# Zerodha Trade Platform

Automated CPR (Central Pivot Range) breakout trading platform built on Zerodha's Kite API. Scans NIFTY sector indices for narrow CPR stocks each morning, identifies the best candidates, and trades breakouts using 5-minute candle confirmation with tick-level stop loss monitoring.

## Architecture

```
Frontend (Next.js 14)              Backend (FastAPI)
+-----------------------+          +----------------------------+
| CPR Trading Desk (/)  |  REST/WS | Provider Abstraction Layer |
| - Scanner results     |<-------->| - Zerodha (live)           |
| - Engine controls     |          | - Mock (paper trading)     |
| - Live positions      |          +----------------------------+
| - Order feed          |          | Trading Engine             |
| - Risk dashboard      |          | - CPR Scanner              |
+-----------------------+          | - CPR Breakout Strategy    |
                                   | - CandleBuilder            |
                                   | - Tick-level SL/target     |
                                   | - Trailing stop loss       |
                                   +----------------------------+
                                   | Risk Manager | Order Mgr   |
                                   +----------------------------+
                                   | PostgreSQL 16 | Redis 7    |
                                   +----------------------------+
```

**Signal pipeline**: CPR Scanner -> Strategy -> RiskManager -> OrderManager -> Zerodha API

**Real-time data**: KiteTicker WebSocket -> Engine -> CandleBuilder (5-min) + on_tick (SL/target) -> Frontend via WebSocket bridge

## Strategy: CPR Breakout

- **CPR Calculation**: `Pivot = (H+L+C)/3`, `BC = (H+L)/2`, `TC = 2*Pivot - BC`
- **Narrow CPR**: Width% < 0.3% indicates high probability of breakout
- **Entry**: LONG when 5-min candle closes above TC, SHORT when below BC
- **Stop Loss**: Opposite CPR boundary, checked on every tick (not just candle close)
- **Trailing SL**: Activates after configurable profit threshold, trails from peak price
- **Target**: Risk/Reward ratio * SL distance (default 2:1)
- **Intraday only**: MIS product type, auto-close at 15:15 IST

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.14, FastAPI, SQLAlchemy, Pydantic |
| Frontend | Next.js 14, React 18, TypeScript, SWR, Tailwind CSS |
| Database | PostgreSQL 16, Redis 7 |
| Broker | Zerodha Kite Connect API, KiteTicker WebSocket |
| Testing | pytest (526+), Jest (94+), 620+ total tests |
| Infra | Docker Compose, Makefile, mkcert (HTTPS) |

## Quick Start

### Prerequisites

- Python 3.12+ with venv
- Node.js 20+ with npm
- Docker and Docker Compose
- Zerodha Kite Connect API credentials (for live trading)

### Setup

```bash
# Clone and install
git clone <repo-url> && cd zerodha-trade

# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Frontend
cd ../frontend && npm install

# Start databases
docker compose up -d postgres redis

# Run dev servers
make dev
```

The backend runs at `https://localhost:8000` and the frontend at `http://localhost:3000`.

### Zerodha Setup

1. Create a Kite Connect app at [developers.kite.trade](https://developers.kite.trade)
2. Set redirect URL to `https://localhost:8000/api/auth/zerodha/callback`
3. Add API key and secret to `.env`:
   ```
   TRADE_DEFAULT_PROVIDER=zerodha
   ZERODHA_API_KEY=your_api_key
   ZERODHA_API_SECRET=your_api_secret
   ```
4. Navigate to `/api/auth/zerodha/login` to complete OAuth

## Key Commands

```bash
make dev              # Start full dev environment (backend + frontend)
make test             # Run all 620+ tests (backend + frontend)
make test-backend     # Run backend tests only
make test-frontend    # Run frontend tests only
make test-cov         # Run tests with coverage
make lint             # Lint all code (ruff + eslint)
make docker-up        # Full Docker deployment
make clean            # Remove build artifacts
make help             # Show all available commands
```

## Project Structure

```
backend/
  app/
    api/routes/        # REST + WebSocket endpoints
    core/              # TradingEngine, RiskManager, OrderManager
    providers/         # Zerodha (live) and Mock (paper) providers
    strategies/        # CPR Breakout strategy
    services/          # NSE Index service, Redis client, session store
    models/            # SQLAlchemy ORM models
  config/              # YAML configuration files
  tests/               # pytest suite (unit, api, e2e)
frontend/
  src/
    app/               # Next.js pages (CPR Trading Desk, Scanner)
    components/        # UI components
    hooks/             # SWR hooks, WebSocket streams
    lib/               # API client, utilities
docs/                  # Detailed documentation (13 files)
```

## How to Use (Daily Trading Workflow)

### 1. Start the Platform

```bash
# Start databases
docker compose up -d postgres redis

# Start dev servers (backend at :8000, frontend at :3000)
make dev
```

Open the frontend at `http://localhost:3000`. Everything happens on the single-page CPR Trading Desk.

### 2. Authenticate with Zerodha

- Click the **Login** button (or navigate to the Settings page)
- Complete Zerodha OAuth login (redirects to Kite and back)
- Session is persisted in the database -- survives server restarts until 6 AM IST

### 3. Run the CPR Scanner

- The scanner runs automatically on page load, or click **Scan** to refresh
- It fetches previous day OHLC from Zerodha for all NIFTY index stocks
- Calculates CPR levels and ranks stocks by width (narrowest first)
- Stocks with width < 0.3% are marked as **Narrow CPR** (high breakout probability)
- Direction signal shows LONG (open > TC), SHORT (open < BC), or WAIT

### 4. Load Picks into the Engine

- Select the narrow CPR stocks you want to trade (or use the auto-selection)
- Click **Load Picks** -- this creates CPR Breakout strategy instances per stock
- Each pick carries its CPR levels (TC, BC, Pivot), direction signal, and width

### 5. Start the Trading Engine

- Click **Start Engine** -- it subscribes to live tick data via KiteTicker WebSocket
- The engine builds 5-minute candles from raw ticks
- When a candle closes above TC (LONG) or below BC (SHORT), a signal fires
- Signals go through: RiskManager checks -> OrderManager -> Zerodha order placement
- Stop loss is monitored on every tick (not just at candle boundaries)
- Trailing stop loss activates after a configurable profit threshold

### 6. Monitor During the Day

- **Live Positions**: Real-time P&L, SL/target levels, trailing SL status
- **Order Feed**: All placed orders with status (OPEN, COMPLETE, REJECTED)
- **Risk Dashboard**: Daily loss tracking, position count, kill switch
- **Engine Events**: Timeline of all scan, signal, order, and fill events
- All data pushed in real-time via WebSocket bridge (no polling)

### 7. End of Day

- The strategy auto-closes all positions at 15:15 IST (3:15 PM)
- Click **Stop Engine** after market close
- Review trades in the order feed

### Paper Trading Mode

Switch between live and paper trading from the **Settings** page:

- **Paper mode** uses real market data from Zerodha but simulates all order fills in-memory
- Orders fill immediately at real-time LTP with configurable slippage (default 0.05%)
- Full position tracking, P&L calculation, and capital management
- Amber banner shows at the top of the dashboard when paper mode is active
- Reset paper session to clear all simulated trades and restore initial capital
- Engine must be stopped before switching modes

```
Settings > Trading Mode > Paper Trading > Save
```

## Documentation

Detailed documentation is in the [`docs/`](docs/) directory:

- [Architecture](docs/architecture.md) -- System design and data flow
- [Getting Started](docs/getting-started.md) -- Full setup guide
- [API Reference](docs/api-reference.md) -- REST and WebSocket endpoints
- [Strategies](docs/strategies.md) -- CPR Breakout strategy details
- [Risk Management](docs/risk-management.md) -- Risk limits and controls
- [Providers](docs/providers.md) -- Zerodha and Mock provider setup
- [Configuration](docs/configuration.md) -- YAML config and environment variables
- [Frontend](docs/frontend.md) -- UI components and hooks
- [Testing](docs/testing.md) -- Test structure and running tests
- [Deployment](docs/deployment.md) -- Docker and production deployment
- [Mock Trading](docs/mock-trading.md) -- Paper trading with mock provider

## Risk Controls

- Max daily loss: 50,000
- Max loss per trade: 10,000
- Risk/Reward ratio: 2:1 (configurable)
- Max open positions: 10
- One trade per day per stock
- All trades are intraday (MIS), auto-closed at 15:15 IST
- Stop loss checked on every tick, not just candle boundaries
- Trailing stop loss moves in direction of profit

## License

Private. Not for redistribution.
