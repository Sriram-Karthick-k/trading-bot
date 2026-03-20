"""
Redis client utility.

Provides an async Redis client singleton for caching across the application.
Used by NSEIndexService for persistent index constituent caching (24h TTL).

Redis is optional — if unavailable, operations gracefully return None/False
so callers can fall back to in-memory caching.

Usage:
    from app.services.redis_client import get_redis, redis_get, redis_set

    # Low-level
    r = await get_redis()
    if r:
        await r.set("key", "value", ex=3600)

    # High-level (with JSON serialization)
    await redis_set("nse:NIFTY 50", data_dict, ttl=86400)
    cached = await redis_get("nse:NIFTY 50")
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None
_redis_unavailable: bool = False  # Set to True after first connection failure


def _get_redis_url() -> str:
    """Resolve Redis URL from environment or default config."""
    return os.environ.get("TRADE_REDIS_URL", "redis://localhost:6379/0")


async def get_redis() -> aioredis.Redis | None:
    """
    Get the async Redis client singleton.

    Returns None if Redis is unavailable (no retry until process restart
    or explicit reset).
    """
    global _redis_client, _redis_unavailable

    if _redis_unavailable:
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        url = _get_redis_url()
        _redis_client = aioredis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
        )
        # Verify connection
        await _redis_client.ping()
        logger.info("Redis connected: %s", url)
        return _redis_client
    except Exception as e:
        logger.warning("Redis unavailable (caching disabled): %s", e)
        _redis_unavailable = True
        _redis_client = None
        return None


async def redis_get(key: str) -> Any | None:
    """
    Get a JSON-deserialized value from Redis.

    Returns None if key doesn't exist or Redis is unavailable.
    """
    r = await get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug("Redis GET failed for %s: %s", key, e)
        return None


async def redis_set(key: str, value: Any, ttl: int = 86400) -> bool:
    """
    Set a JSON-serialized value in Redis with TTL (default 24h).

    Returns True on success, False if Redis is unavailable.
    """
    r = await get_redis()
    if r is None:
        return False
    try:
        raw = json.dumps(value)
        await r.set(key, raw, ex=ttl)
        return True
    except Exception as e:
        logger.debug("Redis SET failed for %s: %s", key, e)
        return False


async def redis_delete(key: str) -> bool:
    """Delete a key from Redis."""
    r = await get_redis()
    if r is None:
        return False
    try:
        await r.delete(key)
        return True
    except Exception as e:
        logger.debug("Redis DELETE failed for %s: %s", key, e)
        return False


async def close_redis() -> None:
    """Close the Redis connection (call on shutdown)."""
    global _redis_client, _redis_unavailable
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None
    _redis_unavailable = False
    logger.debug("Redis connection closed")


def reset_redis() -> None:
    """Reset the Redis state so next get_redis() attempts a fresh connection."""
    global _redis_client, _redis_unavailable
    _redis_client = None
    _redis_unavailable = False
