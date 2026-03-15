"""
RSI (Relative Strength Index) Mean-Reversion Strategy.

Buys when RSI drops below oversold level, sells when RSI rises above overbought level.
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


class RSIStrategy(Strategy):
    """
    RSI Mean-Reversion — buys at oversold, sells at overbought.

    Parameters:
        rsi_period: Lookback period for RSI (default: 14)
        oversold: RSI level considered oversold (default: 30)
        overbought: RSI level considered overbought (default: 70)
        instrument_token: Token of the instrument to trade
        trading_symbol: Symbol name
        exchange: Exchange name (default: NSE)
        quantity: Order quantity per signal (default: 1)
    """

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)
        period = self.get_param("rsi_period", 14)
        self._prices: deque[float] = deque(maxlen=period + 1)
        self._in_position = False

    @classmethod
    def name(cls) -> str:
        return "rsi_mean_reversion"

    @classmethod
    def description(cls) -> str:
        return (
            "RSI Mean-Reversion. Buys when RSI drops below the oversold threshold "
            "and sells when RSI rises above the overbought threshold."
        )

    @classmethod
    def get_params_schema(cls) -> list[ParamDef]:
        return [
            ParamDef(
                name="rsi_period", param_type=ParamType.INT, default=14,
                label="RSI Period", description="Lookback period for RSI calculation",
                min_value=2, max_value=100,
            ),
            ParamDef(
                name="oversold", param_type=ParamType.FLOAT, default=30.0,
                label="Oversold Level", description="Buy signal when RSI drops below this",
                min_value=5, max_value=50,
            ),
            ParamDef(
                name="overbought", param_type=ParamType.FLOAT, default=70.0,
                label="Overbought Level", description="Sell signal when RSI rises above this",
                min_value=50, max_value=95,
            ),
            ParamDef(
                name="instrument_token", param_type=ParamType.INT, default=0,
                label="Instrument Token", description="Numeric token of the instrument",
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

    def _compute_rsi(self) -> float | None:
        period = self.get_param("rsi_period", 14)
        if len(self._prices) < period + 1:
            return None

        prices = list(self._prices)
        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _process_price(self, price: float) -> None:
        self._prices.append(price)
        rsi = self._compute_rsi()
        if rsi is None:
            return

        oversold = self.get_param("oversold", 30.0)
        overbought = self.get_param("overbought", 70.0)
        symbol = self.get_param("trading_symbol", "")
        exchange_str = self.get_param("exchange", "NSE")
        quantity = self.get_param("quantity", 1)

        if rsi < oversold and not self._in_position:
            self._in_position = True
            self._emit_signal(StrategySignal(
                instrument_token=self.get_param("instrument_token", 0),
                trading_symbol=symbol,
                action="BUY",
                reason=f"RSI ({rsi:.1f}) below oversold level ({oversold})",
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
        elif rsi > overbought and self._in_position:
            self._in_position = False
            self._emit_signal(StrategySignal(
                instrument_token=self.get_param("instrument_token", 0),
                trading_symbol=symbol,
                action="SELL",
                reason=f"RSI ({rsi:.1f}) above overbought level ({overbought})",
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
