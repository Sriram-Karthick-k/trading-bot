"""
Mock broker provider for paper trading and testing.

Implements the full BrokerProvider interface using virtual state.
All orders, positions, and portfolio are simulated in-memory.
Uses the MockEngine for fill simulation and the VirtualClock for time.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from app.core.clock import VirtualClock
from app.providers.base import BrokerProvider, OrderError
from app.providers.mock.engine import MockEngine
from app.providers.mock.time_controller import TimeController
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
    MarginSegment,
    OHLCQuote,
    Order,
    OrderRequest,
    OrderResponse,
    OrderType,
    OrderUpdate,
    PositionsData,
    ProductType,
    ProviderInfo,
    Quote,
    Session,
    TickMode,
    Trade,
    Variety,
)

logger = logging.getLogger(__name__)


class MockTicker:
    """Mock ticker that delivers ticks from the mock engine."""

    def __init__(self, engine: MockEngine):
        self._engine = engine
        self._connected = False
        self._on_tick = None
        self._on_order_update = None
        self._on_connect = None
        self._on_disconnect = None
        self._on_error = None
        self._subscriptions: dict[int, TickMode] = {}

    def connect(self) -> None:
        self._connected = True
        if self._on_connect:
            self._on_connect()

    def disconnect(self) -> None:
        self._connected = False
        if self._on_disconnect:
            self._on_disconnect(1000, "Normal closure")

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, instrument_tokens: list[int], mode: TickMode = TickMode.QUOTE) -> None:
        for token in instrument_tokens:
            self._subscriptions[token] = mode

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        for token in instrument_tokens:
            self._subscriptions.pop(token, None)

    def set_on_tick(self, callback) -> None:
        self._on_tick = callback

    def set_on_order_update(self, callback) -> None:
        self._on_order_update = callback

    def set_on_connect(self, callback) -> None:
        self._on_connect = callback

    def set_on_disconnect(self, callback) -> None:
        self._on_disconnect = callback

    def set_on_error(self, callback) -> None:
        self._on_error = callback

    def deliver_ticks(self, ticks: list) -> None:
        """Called by the engine/replayer to deliver ticks."""
        if self._on_tick and self._connected:
            # Filter to only subscribed instruments
            filtered = [t for t in ticks if t.instrument_token in self._subscriptions]
            if filtered:
                self._on_tick(filtered)


class MockProvider(BrokerProvider):
    """
    Simulated broker for paper trading and mock testing.

    All operations happen in-memory. No real orders are placed.
    """

    def __init__(
        self,
        capital: float = 100000.0,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
        clock: VirtualClock | None = None,
        **kwargs: Any,
    ):
        self._clock = clock or VirtualClock()
        self._engine = MockEngine(
            capital=capital,
            slippage_pct=slippage_pct,
            brokerage_per_order=brokerage_per_order,
            clock=self._clock,
        )
        self._ticker = MockTicker(self._engine)
        self._time_controller = TimeController(clock=self._clock)
        self._session: Session | None = None
        self._instruments: list[Instrument] = []
        self._historical_data: dict[str, list[Candle]] = {}  # key: "{token}:{interval}"

    @property
    def engine(self) -> MockEngine:
        return self._engine

    @property
    def clock(self) -> VirtualClock:
        return self._clock

    @property
    def time_controller(self) -> TimeController:
        return self._time_controller

    # ─── Authentication ───────────────────────────────────────────────────

    def get_login_url(self) -> str:
        return "mock://login"

    async def authenticate(self, credentials: Credentials, request_token: str) -> Session:
        self._session = Session(
            user_id="MOCK001",
            access_token=f"mock_{uuid.uuid4().hex[:16]}",
            provider_name="mock",
            login_time=self._clock.now(),
            user_name="Mock Trader",
            email="mock@test.com",
            broker="MOCK",
            exchanges=list(Exchange),
            products=list(ProductType),
            order_types=list(OrderType),
        )
        return self._session

    async def invalidate_session(self) -> bool:
        self._session = None
        return True

    # ─── Orders ───────────────────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        try:
            order_id = self._engine.place_order(order)
            return OrderResponse(order_id=order_id)
        except Exception as e:
            raise OrderError(f"Mock place order failed: {e}")

    async def modify_order(self, order_id: str, order: OrderRequest) -> OrderResponse:
        try:
            self._engine.modify_order(order_id, order)
            return OrderResponse(order_id=order_id)
        except Exception as e:
            raise OrderError(f"Mock modify order failed: {e}")

    async def cancel_order(self, variety: str, order_id: str) -> OrderResponse:
        try:
            self._engine.cancel_order(order_id)
            return OrderResponse(order_id=order_id)
        except Exception as e:
            raise OrderError(f"Mock cancel order failed: {e}")

    async def get_orders(self) -> list[Order]:
        return self._engine.get_orders()

    async def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        return self._engine.get_order_history(order_id)

    async def get_trades(self) -> list[Trade]:
        return self._engine.get_trades()

    async def get_order_trades(self, order_id: str) -> list[Trade]:
        return [t for t in self._engine.get_trades() if t.order_id == order_id]

    # ─── Portfolio ────────────────────────────────────────────────────────

    async def get_positions(self) -> PositionsData:
        return self._engine.get_positions()

    async def get_holdings(self) -> list[Holding]:
        return self._engine.get_holdings()

    # ─── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        return self._engine.get_quotes(instruments)

    async def get_ltp(self, instruments: list[str]) -> dict[str, LTPQuote]:
        return self._engine.get_ltp(instruments)

    async def get_ohlc(self, instruments: list[str]) -> dict[str, OHLCQuote]:
        return self._engine.get_ohlc(instruments)

    async def get_historical(
        self,
        instrument_token: int,
        interval: CandleInterval,
        from_dt: datetime,
        to_dt: datetime,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[Candle]:
        key = f"{instrument_token}:{interval.value}"
        # Check provider-level data first, then fall through to engine
        candles = self._historical_data.get(key) or self._engine._historical.get(key, [])
        # Normalize: strip timezone info for comparison to handle mixed aware/naive
        from_naive = from_dt.replace(tzinfo=None) if from_dt.tzinfo else from_dt
        to_naive = to_dt.replace(tzinfo=None) if to_dt.tzinfo else to_dt
        return [
            c for c in candles
            if from_naive <= c.timestamp.replace(tzinfo=None) <= to_naive
        ]

    def load_historical_data(self, instrument_token: int, interval: CandleInterval, candles: list[Candle]) -> None:
        """Load historical data for mock replay."""
        key = f"{instrument_token}:{interval.value}"
        self._historical_data[key] = sorted(candles, key=lambda c: c.timestamp)

    # ─── Instruments ──────────────────────────────────────────────────────

    async def get_instruments(self, exchange: Exchange | None = None) -> list[Instrument]:
        if exchange:
            return [i for i in self._instruments if i.exchange == exchange]
        return self._instruments

    def load_instruments(self, instruments: list[Instrument]) -> None:
        """Load instrument master for mock."""
        self._instruments = instruments

    # ─── Margins ──────────────────────────────────────────────────────────

    async def get_margins(self, segment: str | None = None) -> MarginsData:
        capital = self._engine.available_capital
        margin = MarginSegment(
            enabled=True,
            net=capital,
            available_cash=capital,
            opening_balance=self._engine.initial_capital,
            live_balance=capital,
            intraday_payin=0,
            adhoc_margin=0,
            collateral=0,
            utilised_debits=self._engine.initial_capital - capital,
            utilised_exposure=0,
            utilised_span=0,
            utilised_option_premium=0,
            utilised_holding_sales=0,
            utilised_turnover=0,
            utilised_m2m_realised=self._engine.realized_pnl,
            utilised_m2m_unrealised=self._engine.unrealized_pnl,
            utilised_payout=0,
            utilised_liquid_collateral=0,
            utilised_stock_collateral=0,
            utilised_delivery=0,
        )
        return MarginsData(equity=margin, commodity=margin)

    # ─── WebSocket / Ticker ───────────────────────────────────────────────

    def create_ticker(self) -> MockTicker:
        return self._ticker

    # ─── Provider Info ────────────────────────────────────────────────────

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            name="mock",
            display_name="Paper Trading (Mock)",
            supported_exchanges=list(Exchange),
            supported_products=list(ProductType),
            supported_order_types=list(OrderType),
            supported_varieties=[Variety.REGULAR, Variety.AMO],
            features={
                "websocket": True,
                "historical_data": True,
                "gtt_orders": False,
                "mutual_funds": False,
                "margin_calculation": True,
                "paper_trading": True,
            },
        )

    async def health_check(self) -> HealthStatus:
        return HealthStatus(
            healthy=True,
            provider_name="mock",
            latency_ms=0.1,
            message="Mock provider always healthy",
            details={
                "capital": self._engine.available_capital,
                "open_orders": len([o for o in self._engine.get_orders() if o.status.value == "OPEN"]),
                "positions": len(self._engine.get_positions().net),
            },
        )
