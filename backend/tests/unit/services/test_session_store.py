"""
Tests for session_store service — session persistence for broker providers.

These tests use pure unit testing with mocks (no real database).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.session_store import (
    _is_token_expired,
    _zerodha_token_expiry,
    deactivate_session,
    load_active_session,
    save_session,
)


# ── Token Expiry Calculation ─────────────────────────────────


class TestZerodhaTokenExpiry:
    """Test _zerodha_token_expiry() calculation."""

    def test_login_before_6am_ist_expires_same_day(self):
        """Login at 3 AM IST → expires at 6 AM IST same day."""
        # 3 AM IST = 9:30 PM UTC previous day
        login_utc = datetime(2026, 3, 14, 21, 30, 0)
        expiry = _zerodha_token_expiry(login_utc)
        # 6 AM IST = 12:30 AM UTC next day
        expected = datetime(2026, 3, 15, 0, 30, 0)
        assert expiry == expected

    def test_login_after_6am_ist_expires_next_day(self):
        """Login at 9 AM IST → expires at 6 AM IST next day."""
        # 9 AM IST = 3:30 AM UTC
        login_utc = datetime(2026, 3, 15, 3, 30, 0)
        expiry = _zerodha_token_expiry(login_utc)
        # 6 AM IST next day = 12:30 AM UTC next next day
        expected = datetime(2026, 3, 16, 0, 30, 0)
        assert expiry == expected

    def test_login_exactly_at_6am_ist_expires_next_day(self):
        """Login at exactly 6 AM IST → expires at 6 AM IST next day."""
        # 6 AM IST = 12:30 AM UTC
        login_utc = datetime(2026, 3, 15, 0, 30, 0)
        expiry = _zerodha_token_expiry(login_utc)
        expected = datetime(2026, 3, 16, 0, 30, 0)
        assert expiry == expected

    def test_login_at_11pm_ist_expires_next_6am(self):
        """Login at 11 PM IST → expires at 6 AM IST next day."""
        # 11 PM IST = 5:30 PM UTC
        login_utc = datetime(2026, 3, 15, 17, 30, 0)
        expiry = _zerodha_token_expiry(login_utc)
        expected = datetime(2026, 3, 16, 0, 30, 0)
        assert expiry == expected


class TestIsTokenExpired:
    """Test _is_token_expired() logic."""

    def test_expired_when_past_expiry(self):
        expires_at = datetime(2026, 3, 15, 0, 30, 0)
        future = datetime(2026, 3, 15, 1, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.session_store.datetime") as mock_dt:
            mock_dt.now.return_value = future
            assert _is_token_expired(expires_at, "zerodha") is True

    def test_not_expired_when_before_expiry(self):
        expires_at = datetime(2026, 3, 15, 0, 30, 0)
        past = datetime(2026, 3, 14, 23, 0, 0, tzinfo=timezone.utc)
        with patch("app.services.session_store.datetime") as mock_dt:
            mock_dt.now.return_value = past
            assert _is_token_expired(expires_at, "zerodha") is False

    def test_expired_when_exactly_at_expiry(self):
        expires_at = datetime(2026, 3, 15, 0, 30, 0)
        exact = datetime(2026, 3, 15, 0, 30, 0, tzinfo=timezone.utc)
        with patch("app.services.session_store.datetime") as mock_dt:
            mock_dt.now.return_value = exact
            assert _is_token_expired(expires_at, "zerodha") is True

    def test_no_expiry_zerodha_assumes_expired(self):
        assert _is_token_expired(None, "zerodha") is True

    def test_no_expiry_mock_assumes_not_expired(self):
        assert _is_token_expired(None, "mock") is False


# ── Save Session ─────────────────────────────────────────────


class TestSaveSession:
    """Test save_session() database operations."""

    @pytest.mark.asyncio
    async def test_save_session_inserts_and_deactivates_old(self):
        """save_session should deactivate old sessions and insert a new one."""
        mock_db = AsyncMock()
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            await save_session(
                provider="zerodha",
                access_token="test_token_123",
                user_id="AB1234",
                meta={"user_name": "Test User"},
            )

        # Should have called execute twice (deactivate + insert via add)
        assert mock_db.execute.call_count == 1  # UPDATE for deactivation
        assert mock_db.add.call_count == 1       # INSERT new session
        assert mock_db.commit.call_count == 1

    @pytest.mark.asyncio
    async def test_save_session_rolls_back_on_error(self):
        """save_session should rollback on database error."""
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB connection failed")
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            with pytest.raises(Exception, match="DB connection failed"):
                await save_session(
                    provider="zerodha",
                    access_token="test_token",
                    user_id="AB1234",
                )

        mock_db.rollback.assert_called_once()


# ── Load Active Session ──────────────────────────────────────


class TestLoadActiveSession:
    """Test load_active_session() database queries."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_session(self):
        """Should return None when no active session exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            result = await load_active_session("zerodha")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_session_when_not_expired(self):
        """Should return session data when token is still valid."""
        mock_row = MagicMock()
        mock_row.access_token = "valid_token"
        mock_row.user_id = "AB1234"
        mock_row.refresh_token = ""
        mock_row.meta = {"user_name": "Test"}
        mock_row.login_time = datetime(2026, 3, 15, 3, 30, 0)
        mock_row.expires_at = datetime(2026, 3, 16, 0, 30, 0)  # future

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            with patch("app.services.session_store._is_token_expired", return_value=False):
                result = await load_active_session("zerodha")

        assert result is not None
        assert result["access_token"] == "valid_token"
        assert result["user_id"] == "AB1234"

    @pytest.mark.asyncio
    async def test_returns_none_and_deactivates_when_expired(self):
        """Should return None and deactivate session when token is expired."""
        mock_row = MagicMock()
        mock_row.access_token = "expired_token"
        mock_row.user_id = "AB1234"
        mock_row.expires_at = datetime(2026, 3, 14, 0, 30, 0)  # past

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            with patch("app.services.session_store._is_token_expired", return_value=True):
                with patch("app.services.session_store.deactivate_session", new_callable=AsyncMock) as mock_deactivate:
                    result = await load_active_session("zerodha")

        assert result is None
        mock_deactivate.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self):
        """Should return None gracefully when DB query fails."""
        mock_db = AsyncMock()
        mock_db.execute.side_effect = Exception("DB unavailable")
        mock_context = AsyncMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_db)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.session_store.async_session_factory", return_value=mock_context):
            result = await load_active_session("zerodha")

        assert result is None


# ── Deactivate Session ───────────────────────────────────────


class TestDeactivateSession:
    """Test deactivate_session() operations."""

    @pytest.mark.asyncio
    async def test_deactivates_all_active_sessions(self):
        """Should issue UPDATE setting is_active=False for provider."""
        mock_db = AsyncMock()

        with patch("app.services.session_store.async_session_factory") as mock_factory:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_db)
            mock_context.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value = mock_context

            await deactivate_session("zerodha")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_provided_db_session(self):
        """Should use the provided DB session instead of creating one."""
        mock_db = AsyncMock()
        await deactivate_session("zerodha", db=mock_db)

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()
