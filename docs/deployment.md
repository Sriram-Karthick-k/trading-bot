# Deployment

## Development (Local)

The recommended local development setup uses Docker for databases and runs application servers natively:

```bash
# Start databases
docker compose up -d postgres redis

# Start backend (terminal 1)
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# Start frontend (terminal 2)
cd frontend && npm run dev

# Or use the Makefile
make dev
```

## Docker Compose (Full Stack)

Deploy all services with a single command:

```bash
make docker-up
# or
docker compose up -d --build
```

### Services

| Service | Port | Image | Description |
|---------|------|-------|-------------|
| `frontend` | 3000 | Custom (./frontend) | Next.js application |
| `backend` | 8000 | Custom (./backend) | FastAPI application |
| `postgres` | 5432 | postgres:16-alpine | PostgreSQL database |
| `redis` | 6379 | redis:7-alpine | Redis cache |

### docker-compose.yml

```yaml
services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    environment:
      - TRADE_DATABASE_URL=postgresql+asyncpg://trade:trade@postgres:5432/zerodha_trade
      - TRADE_REDIS_URL=redis://redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app          # Hot-reload in dev

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    depends_on:
      - backend

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: trade
      POSTGRES_PASSWORD: trade
      POSTGRES_DB: zerodha_trade
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U trade"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  redis_data:
```

### Container Management

```bash
# Start all services
make docker-up

# Stop all services
make docker-down

# View logs
make docker-logs

# Rebuild after code changes
docker compose up -d --build

# Individual service restart
docker compose restart backend
```

## Environment Variables

### Required for Production

| Variable | Description |
|----------|-------------|
| `TRADE_DATABASE_URL` | PostgreSQL connection string |
| `TRADE_REDIS_URL` | Redis connection string |
| `TRADE_ZERODHA_API_KEY` | Kite Connect API key (for live trading) |
| `TRADE_ZERODHA_API_SECRET` | Kite Connect API secret |

### Optional Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADE_APP_DEBUG` | `false` | Debug mode |
| `TRADE_LOG_LEVEL` | `INFO` | Log level |
| `TRADE_DEFAULT_PROVIDER` | `mock` | Default provider |
| `TRADE_MAX_DAILY_LOSS` | `50000` | Max daily loss |
| `TRADE_KILL_SWITCH` | `false` | Kill switch state |

See [Configuration](./configuration.md) for the complete list.

## Database Migrations

```bash
# Run pending migrations
make db-migrate

# Create a new migration
make db-revision msg="add_new_table"
```

## Health Checks

Verify the system is running:

```bash
# Backend health
curl http://localhost:8000/api/health

# Frontend (should return HTML)
curl -s http://localhost:3000 | head -5

# Docker service health
docker compose ps
```

## Production Considerations

- Set `TRADE_APP_DEBUG=false`
- Use strong database credentials
- Configure CORS origins for your domain (in `backend/app/main.py`)
- Store credentials in secrets manager, not `.env` files
- Set up monitoring for risk metrics and kill switch status
- Configure backup for PostgreSQL data volume
- Use HTTPS/WSS for all external connections
- Review and tighten risk limits before live trading
