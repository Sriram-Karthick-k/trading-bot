"""
Persistent session storage for broker provider tokens.

Saves and restores access_token / refresh_token across server restarts
using the ProviderSession SQLAlchemy model.

Zerodha access tokens expire daily at ~6:00 AM IST. This module handles
expiry detection so stale tokens are not restored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import async_session_factory
from app.models.models import ProviderSession

logger = logging.getLogger(__name__)

# IST = UTC+5:30
_IST = timezone(timedelta(hours=5, minutes=30))

# Zerodha tokens expire at 6:00 AM IST each day
_ZERODHA_EXPIRY_HOUR = 6
_ZERODHA_EXPIRY_MINUTE = 0


def _zerodha_token_expiry(login_time: datetime) -> datetime:
    """Calculate when a Zerodha token expires (next 6:00 AM IST after login)."""
    # Convert login_time to IST
    if login_time.tzinfo is None:
        login_ist = login_time.replace(tzinfo=timezone.utc).astimezone(_IST)
    else:
        login_ist = login_time.astimezone(_IST)

    # Expiry is next 6:00 AM IST after login
    expiry_ist = login_ist.replace(
        hour=_ZERODHA_EXPIRY_HOUR, minute=_ZERODHA_EXPIRY_MINUTE,
        second=0, microsecond=0,
    )
    if expiry_ist <= login_ist:
        expiry_ist += timedelta(days=1)

    return expiry_ist.astimezone(timezone.utc).replace(tzinfo=None)


def _is_token_expired(expires_at: datetime | None, provider: str) -> bool:
    """Check if a token has expired."""
    if expires_at is None:
        # No expiry set — for zerodha, assume expired if no info
        return provider == "zerodha"
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return now_utc >= expires_at


async def save_session(
    provider: str,
    access_token: str,
    user_id: str = "",
    refresh_token: str = "",
    meta: dict | None = None,
) -> None:
    """
    Save a provider session to the database.

    Deactivates any existing active sessions for this provider first,
    then inserts a new active session.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Calculate expiry based on provider
    if provider == "zerodha":
        expires_at = _zerodha_token_expiry(now)
    else:
        expires_at = None

    async with async_session_factory() as db:
        try:
            # Deactivate previous active sessions for this provider
            await db.execute(
                update(ProviderSession)
                .where(
                    ProviderSession.provider == provider,
                    ProviderSession.is_active == True,  # noqa: E712
                )
                .values(is_active=False)
            )

            # Insert new active session
            session = ProviderSession(
                provider=provider,
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                is_active=True,
                login_time=now,
                expires_at=expires_at,
                meta=meta,
            )
            db.add(session)
            await db.commit()
            logger.info(
                "Saved session for provider=%s user=%s expires_at=%s",
                provider, user_id, expires_at,
            )
        except Exception as e:
            await db.rollback()
            logger.error("Failed to save session: %s", e)
            raise


async def load_active_session(provider: str) -> dict | None:
    """
    Load the most recent active, non-expired session for a provider.

    Returns a dict with keys: access_token, user_id, refresh_token, meta, login_time, expires_at
    or None if no valid session exists.
    """
    async with async_session_factory() as db:
        try:
            result = await db.execute(
                select(ProviderSession)
                .where(
                    ProviderSession.provider == provider,
                    ProviderSession.is_active == True,  # noqa: E712
                )
                .order_by(ProviderSession.login_time.desc())
                .limit(1)
            )
            row = result.scalar_one_or_none()

            if row is None:
                logger.info("No active session found for provider=%s", provider)
                return None

            # Check expiry
            if _is_token_expired(row.expires_at, provider):
                logger.info(
                    "Session for provider=%s expired at %s, deactivating",
                    provider, row.expires_at,
                )
                await deactivate_session(provider, db=db)
                return None

            logger.info(
                "Loaded active session for provider=%s user=%s (expires %s)",
                provider, row.user_id, row.expires_at,
            )
            return {
                "access_token": row.access_token,
                "user_id": row.user_id,
                "refresh_token": row.refresh_token,
                "meta": row.meta,
                "login_time": row.login_time,
                "expires_at": row.expires_at,
            }
        except Exception as e:
            logger.error("Failed to load session: %s", e)
            return None


async def deactivate_session(
    provider: str, *, db: AsyncSession | None = None,
) -> None:
    """Deactivate all active sessions for a provider."""
    if db is not None:
        # Use the provided session (caller manages lifecycle)
        await db.execute(
            update(ProviderSession)
            .where(
                ProviderSession.provider == provider,
                ProviderSession.is_active == True,  # noqa: E712
            )
            .values(is_active=False)
        )
        await db.commit()
        logger.info("Deactivated sessions for provider=%s", provider)
        return

    # Create our own session
    async with async_session_factory() as own_db:
        try:
            await own_db.execute(
                update(ProviderSession)
                .where(
                    ProviderSession.provider == provider,
                    ProviderSession.is_active == True,  # noqa: E712
                )
                .values(is_active=False)
            )
            await own_db.commit()
            logger.info("Deactivated sessions for provider=%s", provider)
        except Exception as e:
            await own_db.rollback()
            logger.error("Failed to deactivate session: %s", e)
