"""
Simple Moving Average (SMA) Crossover Strategy.

Generates BUY when fast SMA crosses above slow SMA, SELL when it crosses below.
This is a classic trend-following strategy suitable for paper trading practice.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.providers.types import (
    Candle,
    Exchange,
    OrderRequest,
    OrderType,
    ProductType,
    TickData,
    TransactionType,
    Variety,
    Validity,
)
from app.strategies.base import ParamDef, ParamType, Strategy, StrategySignal


class SMAcrossoverStrategy(Strategy):
    """
    SMA Crossover — buy when fast SMA > slow SMA, sell when it reverses.

    Parameters:
        fast_period: Number of candles for the fast moving average (default: 10)
        slow_period: Number of candles for the slow moving average (default: 20)
        instrument_token: Token of the instrument to trade
        trading_symbol: Symbol name (e.g. RELIANCE)
        exchange: Exchange name (default: NSE)
        quantity: Order quantity per signal (default: 1)
    """

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        fast = self.get_param("fast_period", 10)
        slow = self.get_param("slow_period", 20)
        self._fast_prices: deque[float] = deque(maxlen=fast)
        self._slow_prices: deque[float] = deque(maxlen=slow)
        self._prev_fast_above: bool | None = None

    @classmethod
    def name(cls) -> str:
        return "sma_crossover"

    @classmethod
    def description(cls) -> str:
        return (
            "Simple Moving Average Crossover. Buys when fast SMA crosses above "
            "slow SMA (bullish signal), sells when it crosses below (bearish signal)."
        )

    @classmethod
    def get_params_schema(cls) -> list[ParamDef]:
        return [
            ParamDef(
                name="fast_period", param_type=ParamType.INT, default=10,
                label="Fast SMA Period", description="Number of candles for fast MA",
                min_value=2, max_value=100,
            ),
            ParamDef(
                name="slow_period", param_type=ParamType.INT, default=20,
                label="Slow SMA Period", description="Number of candles for slow MA",
                min_value=5, max_value=500,
            ),
            ParamDef(
                name="instrument_token", param_type=ParamType.INT, default=0,
                label="Instrument Token", description="Numeric token of the instrument to trade",
            ),
            ParamDef(
                name="trading_symbol", param_type=ParamType.STRING, default="",
                label="Trading Symbol", description="e.g. RELIANCE, TCS, INFY",
            ),
            ParamDef(
                name="exchange", param_type=ParamType.STRING, default="NSE",
                label="Exchange", description="Exchange (NSE, BSE, NFO, etc.)",
            ),
            ParamDef(
                name="quantity", param_type=ParamType.INT, default=1,
                label="Quantity", description="Shares per order signal",
                min_value=1, max_value=10000,
            ),
        ]

    def get_instruments(self) -> list[int]:
        token = self.get_param("instrument_token", 0)
        return [token] if token else []

    async def on_tick(self, tick: TickData) -> None:
        if tick.instrument_token != self.get_param("instrument_token"):
            return
        self._process_price(tick.last_price)

    async def on_candle(self, instrument_token: int, candle: Candle) -> None:
        if instrument_token != self.get_param("instrument_token"):
            return
        self._process_price(candle.close)

    def _process_price(self, price: float) -> None:
        self._fast_prices.append(price)
        self._slow_prices.append(price)

        fast_period = self.get_param("fast_period", 10)
        slow_period = self.get_param("slow_period", 20)

        if len(self._fast_prices) < fast_period or len(self._slow_prices) < slow_period:
            return  # Not enough data yet

        fast_sma = sum(self._fast_prices) / len(self._fast_prices)
        slow_sma = sum(self._slow_prices) / len(self._slow_prices)
        fast_above = fast_sma > slow_sma

        if self._prev_fast_above is not None and fast_above != self._prev_fast_above:
            symbol = self.get_param("trading_symbol", "")
            exchange_str = self.get_param("exchange", "NSE")
            quantity = self.get_param("quantity", 1)

            if fast_above:
                # Bullish crossover — BUY
                self._emit_signal(StrategySignal(
                    instrument_token=self.get_param("instrument_token", 0),
                    trading_symbol=symbol,
                    action="BUY",
                    reason=f"Fast SMA ({fast_sma:.2f}) crossed above Slow SMA ({slow_sma:.2f})",
                    order_request=OrderRequest(
                        tradingsymbol=symbol,
                        exchange=Exchange(exchange_str),
                        transaction_type=TransactionType.BUY,
                        order_type=OrderType.MARKET,
                        quantity=quantity,
                        product=ProductType.CNC,
                        variety=Variety.REGULAR,
                        validity=Validity.DAY,
                    ),
                ))
            else:
                # Bearish crossover — SELL
                self._emit_signal(StrategySignal(
                    instrument_token=self.get_param("instrument_token", 0),
                    trading_symbol=symbol,
                    action="SELL",
                    reason=f"Fast SMA ({fast_sma:.2f}) crossed below Slow SMA ({slow_sma:.2f})",
                    order_request=OrderRequest(
                        tradingsymbol=symbol,
                        exchange=Exchange(exchange_str),
                        transaction_type=TransactionType.SELL,
                        order_type=OrderType.MARKET,
                        quantity=quantity,
                        product=ProductType.CNC,
                        variety=Variety.REGULAR,
                        validity=Validity.DAY,
                    ),
                ))

        self._prev_fast_above = fast_above
