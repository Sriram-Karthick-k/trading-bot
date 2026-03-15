# Zerodha Trade Platform — Documentation

Comprehensive documentation for the Zerodha Trade Platform, a multi-provider automated trading system.

## Table of Contents

| Document | Description |
|----------|-------------|
| [Architecture](./architecture.md) | System architecture, design patterns, and component relationships |
| [Getting Started](./getting-started.md) | Setup, installation, and first run guide |
| [Configuration](./configuration.md) | All configurable options, YAML files, environment variables, and overrides |
| [API Reference](./api-reference.md) | Complete REST API documentation with request/response schemas |
| [Providers](./providers.md) | Broker provider abstraction, Zerodha integration, and Mock engine |
| [Strategies](./strategies.md) | Strategy framework, lifecycle, parameter schemas, and signal pipeline |
| [Risk Management](./risk-management.md) | Pre-trade risk checks, kill switch, and daily loss tracking |
| [Mock Trading](./mock-trading.md) | Paper trading engine, virtual clock, time controls, and replay system |
| [Frontend](./frontend.md) | Next.js frontend architecture, pages, components, hooks, and data flow |
| [Testing](./testing.md) | Test structure, running tests, and writing new tests |
| [Deployment](./deployment.md) | Docker Compose, production deployment, and environment setup |

## Quick Reference

```
Backend:    Python 3.14 · FastAPI · SQLAlchemy · Pydantic
Frontend:   Next.js 14 · React 18 · TypeScript · Tailwind CSS
Database:   PostgreSQL 16 · Redis 7
Testing:    pytest (backend) · Jest + Testing Library (frontend)
Infra:      Docker Compose · Makefile
```

## Project Structure

```
zerodha-trade/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── api/
│   │   │   ├── deps.py             # Dependency injection
│   │   │   └── routes/             # API route handlers
│   │   ├── core/
│   │   │   ├── config_manager.py   # Three-layer config
│   │   │   ├── risk_manager.py     # Pre-trade risk engine
│   │   │   ├── order_manager.py    # Signal-to-order pipeline
│   │   │   └── clock.py            # Clock abstraction
│   │   ├── models/
│   │   │   └── models.py           # SQLAlchemy ORM models
│   │   ├── providers/
│   │   │   ├── base.py             # Abstract provider interface
│   │   │   ├── types.py            # Unified data types
│   │   │   ├── registry.py         # Provider lifecycle
│   │   │   ├── zerodha/            # Kite Connect implementation
│   │   │   └── mock/               # Paper trading engine
│   │   └── strategies/
│   │       └── base.py             # Strategy abstract class
│   ├── config/                     # YAML config files
│   ├── tests/                      # pytest test suite
│   └── .venv/                      # Python virtual environment
├── frontend/
│   ├── src/
│   │   ├── app/                    # Next.js pages
│   │   ├── components/             # Reusable UI components
│   │   ├── hooks/                  # React hooks
│   │   ├── lib/                    # API client & utilities
│   │   ├── types/                  # TypeScript interfaces
│   │   └── __tests__/              # Jest test suite
│   ├── jest.config.js
│   └── jest.setup.ts
├── docs/                           # This documentation
├── docker-compose.yml
├── Makefile
└── .env.example
```
