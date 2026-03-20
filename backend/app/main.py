"""
FastAPI application entry point.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load .env from project root (parent of backend/)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    # Fallback: try .env in current working directory
    load_dotenv()

from app.api.routes import auth, orders, portfolio, market, strategies, mock, providers, config, postback, backtest, engine, ws, journal
from app.providers.registry import discover_providers
from app.db.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Zerodha Trade Platform...")

    # Initialize database tables
    try:
        await init_db()
        logger.info("Database tables initialized")
    except Exception as e:
        logger.warning("Database init skipped (DB may not be available): %s", e)

    discover_providers()
    logger.info("Providers discovered")

    # Restore trading mode from config/DB
    try:
        from app.api.deps import get_config_manager, set_trading_mode
        config_mgr = get_config_manager()
        saved_mode = config_mgr.get("trading.mode", str, default="live")
        if saved_mode == "paper":
            set_trading_mode("paper")
            logger.info("Restored trading mode: paper")
        else:
            logger.info("Trading mode: live")
    except Exception as e:
        logger.warning("Failed to restore trading mode: %s", e)

    # Restore saved session for Zerodha provider
    try:
        from app.providers.registry import get_active_provider_name, get_active_provider
        from app.services.session_store import load_active_session

        if get_active_provider_name() == "zerodha":
            saved = await load_active_session("zerodha")
            if saved and saved.get("access_token"):
                from app.providers.zerodha.provider import ZerodhaProvider
                provider = get_active_provider()
                if isinstance(provider, ZerodhaProvider):
                    provider._access_token = saved["access_token"]
                    if provider._kite is not None:
                        provider._kite.set_access_token(saved["access_token"])
                    logger.info(
                        "Restored Zerodha session for user=%s (expires %s)",
                        saved.get("user_id"), saved.get("expires_at"),
                    )
    except Exception as e:
        logger.warning("Failed to restore saved session: %s", e)

    # Auto-load sample data for mock provider so instruments are available
    try:
        from app.providers.registry import get_active_provider_name, get_active_provider
        if get_active_provider_name() == "mock":
            from app.providers.mock.provider import MockProvider
            provider = get_active_provider()
            if isinstance(provider, MockProvider):
                provider.engine.load_sample_data()
                provider.load_instruments(provider.engine.get_sample_as_instruments())
                logger.info("Mock provider: loaded %d sample instruments", len(provider._instruments))
    except Exception as e:
        logger.warning("Failed to auto-load mock sample data: %s", e)

    yield
    # Shutdown
    logger.info("Shutting down...")
    try:
        from app.services.redis_client import close_redis
        await close_redis()
    except Exception:
        pass


app = FastAPI(
    title="Zerodha Trade Platform",
    description="Multi-provider automated trading platform with mock testing",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for frontend (HTTP and HTTPS local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(auth.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(strategies.router, prefix="/api")
app.include_router(mock.router, prefix="/api")
app.include_router(providers.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(postback.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(engine.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
app.include_router(journal.router, prefix="/api")


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
