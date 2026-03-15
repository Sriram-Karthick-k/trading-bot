"""
Abstract base class for all broker providers.

Every broker integration (Zerodha, MockProvider, future providers)
must implement this interface. The strategy engine, risk manager,
and order manager interact exclusively through this abstraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.providers.types import (
    Candle,
    CandleInterval,
    Credentials,
    Exchange,
    HealthStatus,
    Holding,
    Instrument,
    LTPQuote,
    MarginsData,
    OHLCQuote,
    Order,
    OrderRequest,
    OrderResponse,
    OrderUpdate,
    PositionsData,
    ProviderInfo,
    Quote,
    Session,
    TickerConnection,
    Trade,
)


class BrokerProvider(ABC):
    """
    Abstract broker provider interface.

    All methods raise `ProviderError` subclasses on failure.
    Implementations must be thread-safe for concurrent access.
    """

    # ─── Authentication ───────────────────────────────────────────────────

    @abstractmethod
    def get_login_url(self) -> str:
        """Return the URL to redirect the user to for OAuth login."""

    @abstractmethod
    async def authenticate(self, credentials: Credentials, request_token: str) -> Session:
        """
        Exchange request_token for access_token.
        Returns a Session with the access_token and user info.
        """

    @abstractmethod
    async def invalidate_session(self) -> bool:
        """Logout / invalidate current session."""

    # ─── Orders ───────────────────────────────────────────────────────────

    @abstractmethod
    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a new order. Returns order_id on success."""

    @abstractmethod
    async def modify_order(self, order_id: str, order: OrderRequest) -> OrderResponse:
        """Modify an existing open/pending order."""

    @abstractmethod
    async def cancel_order(self, variety: str, order_id: str) -> OrderResponse:
        """Cancel an open/pending order."""

    @abstractmethod
    async def get_orders(self) -> list[Order]:
        """Get all orders for the current trading day."""

    @abstractmethod
    async def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        """Get the state transition history of a specific order."""

    @abstractmethod
    async def get_trades(self) -> list[Trade]:
        """Get all trades (fills) for the current trading day."""

    @abstractmethod
    async def get_order_trades(self, order_id: str) -> list[Trade]:
        """Get trades spawned by a specific order."""

    # ─── Portfolio ────────────────────────────────────────────────────────

    @abstractmethod
    async def get_positions(self) -> PositionsData:
        """Get all positions (net and day)."""

    @abstractmethod
    async def get_holdings(self) -> list[Holding]:
        """Get long-term equity holdings."""

    # ─── Market Data ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        """
        Get full market quotes.
        instruments: list of 'exchange:tradingsymbol' strings.
        Max 500 instruments per call.
        """

    @abstractmethod
    async def get_ltp(self, instruments: list[str]) -> dict[str, LTPQuote]:
        """
        Get last traded price only.
        Max 1000 instruments per call.
        """

    @abstractmethod
    async def get_ohlc(self, instruments: list[str]) -> dict[str, OHLCQuote]:
        """
        Get OHLC + LTP quotes.
        Max 1000 instruments per call.
        """

    @abstractmethod
    async def get_historical(
        self,
        instrument_token: int,
        interval: CandleInterval,
        from_dt: datetime,
        to_dt: datetime,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[Candle]:
        """Fetch historical OHLCV candle data."""

    # ─── Instruments ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_instruments(self, exchange: Exchange | None = None) -> list[Instrument]:
        """
        Get tradable instruments.
        If exchange is None, returns instruments across all exchanges.
        """

    # ─── Margins ──────────────────────────────────────────────────────────

    @abstractmethod
    async def get_margins(self, segment: str | None = None) -> MarginsData:
        """Get funds and margin information."""

    # ─── WebSocket / Ticker ───────────────────────────────────────────────

    @abstractmethod
    def create_ticker(self) -> TickerConnection:
        """
        Create a new ticker connection.
        The connection is not started until `connect()` is called.
        """

    # ─── Provider Info ────────────────────────────────────────────────────

    @abstractmethod
    def get_provider_info(self) -> ProviderInfo:
        """Return metadata about this provider (name, capabilities, etc.)."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check if the provider is healthy and reachable."""


# ─── Exceptions ───────────────────────────────────────────────────────────────


class ProviderError(Exception):
    """Base exception for all provider errors."""

    def __init__(self, message: str, code: str = "PROVIDER_ERROR", data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.data = data or {}


class AuthenticationError(ProviderError):
    """Failed to authenticate with the provider."""

    def __init__(self, message: str = "Authentication failed", data: dict | None = None):
        super().__init__(message, code="AUTH_ERROR", data=data)


class OrderError(ProviderError):
    """Failed to place/modify/cancel an order."""

    def __init__(self, message: str = "Order operation failed", data: dict | None = None):
        super().__init__(message, code="ORDER_ERROR", data=data)


class DataError(ProviderError):
    """Failed to retrieve market data or instruments."""

    def __init__(self, message: str = "Data retrieval failed", data: dict | None = None):
        super().__init__(message, code="DATA_ERROR", data=data)


class ConnectionError(ProviderError):
    """WebSocket or network connection failure."""

    def __init__(self, message: str = "Connection failed", data: dict | None = None):
        super().__init__(message, code="CONNECTION_ERROR", data=data)


class InsufficientFundsError(OrderError):
    """Insufficient margin/funds for the order."""

    def __init__(self, message: str = "Insufficient funds", data: dict | None = None):
        super().__init__(message, data=data)
        self.code = "INSUFFICIENT_FUNDS"


class RateLimitError(ProviderError):
    """API rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded", data: dict | None = None):
        super().__init__(message, code="RATE_LIMIT", data=data)
