"""
Zerodha/Kite Connect provider implementation.

Wraps the official kiteconnect Python SDK, mapping all responses
to provider-agnostic types from providers/types.py.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.providers.base import (
    AuthenticationError,
    BrokerProvider,
    DataError,
    OrderError,
    ProviderError,
)
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
    OrderType,
    OrderUpdate,
    PositionsData,
    ProductType,
    ProviderInfo,
    Quote,
    Session,
    TickerConnection,
    Trade,
    Variety,
)
from app.providers.zerodha.mapper import ZerodhaMapper

logger = logging.getLogger(__name__)


class ZerodhaProvider(BrokerProvider):
    """
    Zerodha Kite Connect v3 provider.

    Requires `kiteconnect` package: pip install kiteconnect
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        access_token: str = "",
        **kwargs: Any,
    ):
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._kite = None
        self._ticker = None
        self._mapper = ZerodhaMapper()

        if api_key:
            self._init_kite(api_key, access_token)

    def _init_kite(self, api_key: str, access_token: str = "") -> None:
        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=api_key)
            if access_token:
                self._kite.set_access_token(access_token)
        except ImportError:
            raise ProviderError(
                "kiteconnect package not installed. Run: pip install kiteconnect"
            )

    def _ensure_kite(self) -> Any:
        if self._kite is None:
            raise AuthenticationError("Kite client not initialized. Set api_key first.")
        return self._kite

    # ─── Authentication ───────────────────────────────────────────────────

    def get_login_url(self) -> str:
        kite = self._ensure_kite()
        return kite.login_url()

    async def authenticate(self, credentials: Credentials, request_token: str) -> Session:
        try:
            if not self._kite:
                self._init_kite(credentials.api_key)
            kite = self._ensure_kite()
            self._api_secret = credentials.api_secret

            data = kite.generate_session(request_token, api_secret=credentials.api_secret)
            kite.set_access_token(data["access_token"])
            self._access_token = data["access_token"]

            return self._mapper.to_session(data, "zerodha")
        except Exception as e:
            raise AuthenticationError(f"Kite auth failed: {e}")

    async def invalidate_session(self) -> bool:
        try:
            kite = self._ensure_kite()
            kite.invalidate_access_token(self._access_token)
            return True
        except Exception as e:
            raise AuthenticationError(f"Logout failed: {e}")

    # ─── Orders ───────────────────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        try:
            kite = self._ensure_kite()
            params = self._mapper.from_order_request(order)
            order_id = kite.place_order(**params)
            return OrderResponse(order_id=str(order_id))
        except Exception as e:
            raise OrderError(f"Place order failed: {e}")

    async def modify_order(self, order_id: str, order: OrderRequest) -> OrderResponse:
        try:
            kite = self._ensure_kite()
            params = self._mapper.from_order_request(order)
            params["order_id"] = order_id
            variety = params.pop("variety", "regular")
            kite.modify_order(variety=variety, order_id=order_id, **params)
            return OrderResponse(order_id=order_id)
        except Exception as e:
            raise OrderError(f"Modify order failed: {e}")

    async def cancel_order(self, variety: str, order_id: str) -> OrderResponse:
        try:
            kite = self._ensure_kite()
            kite.cancel_order(variety=variety, order_id=order_id)
            return OrderResponse(order_id=order_id)
        except Exception as e:
            raise OrderError(f"Cancel order failed: {e}")

    async def get_orders(self) -> list[Order]:
        try:
            kite = self._ensure_kite()
            orders = kite.orders()
            return [self._mapper.to_order(o) for o in orders]
        except Exception as e:
            raise DataError(f"Get orders failed: {e}")

    async def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        try:
            kite = self._ensure_kite()
            history = kite.order_history(order_id)
            return [self._mapper.to_order_update(h) for h in history]
        except Exception as e:
            raise DataError(f"Get order history failed: {e}")

    async def get_trades(self) -> list[Trade]:
        try:
            kite = self._ensure_kite()
            trades = kite.trades()
            return [self._mapper.to_trade(t) for t in trades]
        except Exception as e:
            raise DataError(f"Get trades failed: {e}")

    async def get_order_trades(self, order_id: str) -> list[Trade]:
        try:
            kite = self._ensure_kite()
            trades = kite.order_trades(order_id)
            return [self._mapper.to_trade(t) for t in trades]
        except Exception as e:
            raise DataError(f"Get order trades failed: {e}")

    # ─── Portfolio ────────────────────────────────────────────────────────

    async def get_positions(self) -> PositionsData:
        try:
            kite = self._ensure_kite()
            data = kite.positions()
            return self._mapper.to_positions_data(data)
        except Exception as e:
            raise DataError(f"Get positions failed: {e}")

    async def get_holdings(self) -> list[Holding]:
        try:
            kite = self._ensure_kite()
            holdings = kite.holdings()
            return [self._mapper.to_holding(h) for h in holdings]
        except Exception as e:
            raise DataError(f"Get holdings failed: {e}")

    # ─── Market Data ──────────────────────────────────────────────────────

    async def get_quote(self, instruments: list[str]) -> dict[str, Quote]:
        try:
            kite = self._ensure_kite()
            data = kite.quote(instruments)
            return {k: self._mapper.to_quote(v) for k, v in data.items()}
        except Exception as e:
            raise DataError(f"Get quote failed: {e}")

    async def get_ltp(self, instruments: list[str]) -> dict[str, LTPQuote]:
        try:
            kite = self._ensure_kite()
            data = kite.ltp(instruments)
            return {k: self._mapper.to_ltp_quote(v) for k, v in data.items()}
        except Exception as e:
            raise DataError(f"Get LTP failed: {e}")

    async def get_ohlc(self, instruments: list[str]) -> dict[str, OHLCQuote]:
        try:
            kite = self._ensure_kite()
            data = kite.ohlc(instruments)
            return {k: self._mapper.to_ohlc_quote(v) for k, v in data.items()}
        except Exception as e:
            raise DataError(f"Get OHLC failed: {e}")

    async def get_historical(
        self,
        instrument_token: int,
        interval: CandleInterval,
        from_dt: datetime,
        to_dt: datetime,
        continuous: bool = False,
        oi: bool = False,
    ) -> list[Candle]:
        try:
            kite = self._ensure_kite()
            data = kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_dt,
                to_date=to_dt,
                interval=interval.value,
                continuous=continuous,
                oi=oi,
            )
            return [self._mapper.to_candle(c) for c in data]
        except Exception as e:
            raise DataError(f"Get historical data failed: {e}")

    # ─── Instruments ──────────────────────────────────────────────────────

    async def get_instruments(self, exchange: Exchange | None = None) -> list[Instrument]:
        try:
            kite = self._ensure_kite()
            if exchange:
                data = kite.instruments(exchange=exchange.value)
            else:
                data = kite.instruments()
            return [self._mapper.to_instrument(i) for i in data]
        except Exception as e:
            raise DataError(f"Get instruments failed: {e}")

    # ─── Margins ──────────────────────────────────────────────────────────

    async def get_margins(self, segment: str | None = None) -> MarginsData:
        try:
            kite = self._ensure_kite()
            if segment:
                data = kite.margins(segment=segment)
                return self._mapper.to_margins_data({segment: data})
            else:
                data = kite.margins()
                return self._mapper.to_margins_data(data)
        except Exception as e:
            raise DataError(f"Get margins failed: {e}")

    # ─── WebSocket / Ticker ───────────────────────────────────────────────

    def create_ticker(self) -> TickerConnection:
        from app.providers.zerodha.ticker import ZerodhaTicker
        return ZerodhaTicker(self._api_key, self._access_token)

    # ─── Provider Info ────────────────────────────────────────────────────

    def get_provider_info(self) -> ProviderInfo:
        return ProviderInfo(
            name="zerodha",
            display_name="Zerodha (Kite Connect)",
            supported_exchanges=[
                Exchange.NSE, Exchange.BSE, Exchange.NFO,
                Exchange.CDS, Exchange.BCD, Exchange.MCX,
                Exchange.BFO, Exchange.MF,
            ],
            supported_products=[
                ProductType.CNC, ProductType.NRML,
                ProductType.MIS, ProductType.MTF,
            ],
            supported_order_types=[
                OrderType.MARKET, OrderType.LIMIT,
                OrderType.STOPLOSS, OrderType.STOPLOSS_MARKET,
            ],
            supported_varieties=[
                Variety.REGULAR, Variety.AMO, Variety.CO,
                Variety.ICEBERG, Variety.AUCTION,
            ],
            features={
                "websocket": True,
                "historical_data": True,
                "gtt_orders": True,
                "mutual_funds": True,
                "margin_calculation": True,
            },
        )

    async def health_check(self) -> HealthStatus:
        import time
        try:
            kite = self._ensure_kite()
            start = time.monotonic()
            kite.profile()
            latency = (time.monotonic() - start) * 1000
            return HealthStatus(
                healthy=True,
                provider_name="zerodha",
                latency_ms=latency,
                message="Connected",
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                provider_name="zerodha",
                message=str(e),
            )
