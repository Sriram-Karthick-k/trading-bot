# Getting Started

## Prerequisites

- **Python 3.12+** (backend)
- **Node.js 20+** (frontend)
- **Docker & Docker Compose** (databases)
- **Make** (optional, for convenience commands)

## Quick Start

### 1. Clone and Setup Environment

```bash
# Clone the repository
git clone <repo-url> zerodha-trade
cd zerodha-trade

# Copy environment file
cp .env.example .env
```

### 2. Install Dependencies

```bash
# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Linux/Mac
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt
pip install -r requirements-test.txt  # for testing

# Frontend
cd ../frontend
npm install
```

Or using Makefile:

```bash
make install-backend
make install-frontend
```

### 3. Start Databases

```bash
docker compose up -d postgres redis
```

### 4. Start Development Servers

```bash
# Option A: Using Makefile (starts both + databases)
make dev

# Option B: Manual start
# Terminal 1 — Backend
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

### 5. Access the Application

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| Health Check | http://localhost:8000/api/health |

### 6. Run Tests

```bash
make test              # Run all tests (backend + frontend)
make test-backend      # Backend only (103 tests)
make test-frontend     # Frontend only (74 tests)
make test-cov          # Tests with coverage report
```

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make help` | Show all available commands |
| `make dev` | Start all services (postgres, redis, backend, frontend) |
| `make backend` | Start backend server only |
| `make frontend` | Start frontend dev server only |
| `make test` | Run all tests |
| `make test-backend` | Run backend tests |
| `make test-frontend` | Run frontend tests |
| `make test-unit` | Run backend unit tests |
| `make test-api` | Run backend API tests |
| `make test-cov` | Run tests with coverage |
| `make lint` | Lint all code (ruff + eslint) |
| `make clean` | Remove build artifacts |
| `make docker-up` | Full Docker Compose deployment |
| `make docker-down` | Stop all containers |
| `make docker-logs` | View container logs |
| `make install-backend` | Install Python dependencies |
| `make install-frontend` | Install Node dependencies |

## First-Time Workflow

1. **Start with Mock Provider** (default) — no Zerodha account needed
2. Go to **Mock Testing** page → Create a session with starting capital
3. Use **Time Controls** to advance market time
4. Go to **Orders** → Place a test order
5. Check **Portfolio** → See positions and P&L
6. Try **Settings** → Adjust risk limits

## Zerodha Live Trading Setup

1. Register at [Kite Connect](https://kite.trade/) and get API credentials
2. Set environment variables:
   ```bash
   TRADE_ZERODHA_API_KEY=your_api_key
   TRADE_ZERODHA_API_SECRET=your_api_secret
   TRADE_DEFAULT_PROVIDER=zerodha
   ```
3. Go to **Providers** page → Activate Zerodha provider
4. Complete OAuth login flow via the redirect URL
5. Once authenticated, all trading operations use live Kite Connect API
