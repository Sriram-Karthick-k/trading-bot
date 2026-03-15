"""
Backtester — replays historical candles through a strategy and mock engine.

Fetches real data from the active provider (Zerodha if authenticated) or
uses mock synthetic data as fallback, then runs the strategy candle-by-candle
and tracks all trades, signals, and P&L.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from app.core.clock import VirtualClock
from app.providers.mock.engine import MockEngine
from app.providers.mock.provider import MockProvider
from app.providers.base import BrokerProvider
from app.providers.types import (
    Candle,
    CandleInterval,
    OrderRequest,
)
from app.strategies.base import Strategy, StrategySignal

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """A single trade executed during backtesting."""
    timestamp: str
    action: str  # BUY or SELL
    symbol: str
    quantity: int
    price: float
    order_id: str
    reason: str
    signal_confidence: float = 1.0


@dataclass
class BacktestResult:
    """Complete results from a backtest run."""
    strategy_name: str
    symbol: str
    interval: str
    from_date: str
    to_date: str
    initial_capital: float
    final_capital: float
    total_pnl: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    max_drawdown: float
    total_signals: int
    total_candles: int
    data_source: str  # "zerodha" or "mock_synthetic"
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    candles: list[dict] = field(default_factory=list)


async def fetch_candles(
    provider: BrokerProvider,
    instrument_token: int,
    interval: CandleInterval,
    from_dt: datetime,
    to_dt: datetime,
) -> tuple[list[Candle], str]:
    """
    Fetch historical candles — tries the active provider first,
    falls back to mock synthetic data if that fails.
    Returns (candles, data_source_name).
    """
    # 1. Try the active provider
    try:
        candles = await provider.get_historical(
            instrument_token=instrument_token,
            interval=interval,
            from_dt=from_dt,
            to_dt=to_dt,
        )
        if candles:
            source = type(provider).__name__
            if "Zerodha" in source:
                return candles, "zerodha"
            return candles, "mock_synthetic"
    except Exception as e:
        logger.warning("Failed to fetch from active provider: %s", e)

    # 2. Fallback: try mock provider's synthetic data
    if not isinstance(provider, MockProvider):
        try:
            logger.info("Falling back to mock synthetic data for backtest")
            mock = MockProvider()
            mock.engine.load_sample_data()
            mock.load_instruments(mock.engine.get_sample_as_instruments())
            candles = await mock.get_historical(
                instrument_token=instrument_token,
                interval=interval,
                from_dt=from_dt,
                to_dt=to_dt,
            )
            if candles:
                return candles, "mock_synthetic"
        except Exception as e:
            logger.warning("Mock fallback also failed: %s", e)

    return [], "none"


async def run_backtest(
    strategy: Strategy,
    provider: BrokerProvider,
    instrument_token: int,
    tradingsymbol: str,
    exchange: str,
    interval: CandleInterval,
    from_dt: datetime,
    to_dt: datetime,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """
    Run a complete backtest:
    1. Fetch real historical candles from the provider
    2. Create a fresh mock engine
    3. Replay candles through the strategy
    4. Execute signals in the mock engine
    5. Return full results with trade log and equity curve
    """
    # 1. Fetch candles
    candles, data_source = await fetch_candles(
        provider, instrument_token, interval, from_dt, to_dt,
    )

    if not candles:
        return BacktestResult(
            strategy_name=strategy.name(),
            symbol=tradingsymbol,
            interval=interval.value,
            from_date=from_dt.strftime("%Y-%m-%d"),
            to_date=to_dt.strftime("%Y-%m-%d"),
            initial_capital=initial_capital,
            final_capital=initial_capital,
            total_pnl=0,
            total_return_pct=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate=0,
            max_drawdown=0,
            total_signals=0,
            total_candles=0,
            data_source="none",
        )

    # 2. Create a fresh mock engine for this backtest
    clock = VirtualClock(initial_time=candles[0].timestamp)
    engine = MockEngine(
        capital=initial_capital,
        slippage_pct=0.05,
        brokerage_per_order=20.0,
        clock=clock,
    )
    engine.register_instrument(exchange, tradingsymbol, instrument_token)

    # 3. Start the strategy
    await strategy.start()

    # 4. Replay candles
    trade_records: list[TradeRecord] = []
    equity_curve: list[dict] = []
    peak_equity = initial_capital
    max_drawdown = 0.0

    for candle in candles:
        # Advance virtual clock
        clock.set_time(candle.timestamp)

        # Update engine LTP
        engine.set_ltp(instrument_token, candle.close)

        # Feed candle to strategy
        await strategy.on_candle(instrument_token, candle)

        # Collect and execute signals
        signals = strategy.consume_signals()
        for signal in signals:
            if signal.order_request:
                try:
                    order_id = engine.place_order(signal.order_request)
                    order = engine._orders.get(order_id)
                    if order:
                        trade_records.append(TradeRecord(
                            timestamp=candle.timestamp.isoformat(),
                            action=signal.action,
                            symbol=tradingsymbol,
                            quantity=order.quantity,
                            price=order.average_price,
                            order_id=order_id,
                            reason=signal.reason,
                            signal_confidence=signal.confidence,
                        ))
                except Exception as e:
                    logger.warning("Backtest order failed: %s", e)

        # Track equity curve
        current_equity = engine.available_capital + sum(
            engine.get_current_price(p.instrument_token) * abs(p.quantity)
            for p in engine._positions.values()
            if p.quantity != 0
        )
        peak_equity = max(peak_equity, current_equity)
        drawdown = (peak_equity - current_equity) / peak_equity * 100 if peak_equity > 0 else 0
        max_drawdown = max(max_drawdown, drawdown)

        equity_curve.append({
            "timestamp": candle.timestamp.isoformat(),
            "equity": round(current_equity, 2),
            "drawdown": round(drawdown, 2),
        })

    # 5. Stop strategy
    await strategy.stop()

    # 6. Calculate final results
    final_equity = engine.available_capital
    # Add value of open positions
    for pos in engine._positions.values():
        if pos.quantity != 0:
            ltp = engine.get_current_price(pos.instrument_token)
            if pos.quantity > 0:
                final_equity += ltp * pos.quantity
            else:
                final_equity += (2 * pos.average_price - ltp) * abs(pos.quantity)

    total_pnl = final_equity - initial_capital
    total_return_pct = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0

    # Count winning/losing by pairing BUY/SELL trades
    winning_trades = 0
    losing_trades = 0
    open_price: float | None = None
    open_action: str | None = None
    for t in trade_records:
        if open_action is None:
            # First trade opens a position
            open_price = t.price
            open_action = t.action
        elif t.action != open_action:
            # Closing trade — opposite direction
            if open_action == "BUY":
                pnl = t.price - (open_price or 0)
            else:
                pnl = (open_price or 0) - t.price
            if pnl > 0:
                winning_trades += 1
            else:
                losing_trades += 1
            open_price = None
            open_action = None
        else:
            # Same direction — averaging into position, update entry price
            open_price = t.price

    total_trades = len(trade_records)
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0

    # Build candle summary (limit to avoid huge response)
    candle_data = [
        {
            "timestamp": c.timestamp.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in candles
    ]

    return BacktestResult(
        strategy_name=strategy.name(),
        symbol=tradingsymbol,
        interval=interval.value,
        from_date=from_dt.strftime("%Y-%m-%d"),
        to_date=to_dt.strftime("%Y-%m-%d"),
        initial_capital=initial_capital,
        final_capital=round(final_equity, 2),
        total_pnl=round(total_pnl, 2),
        total_return_pct=round(total_return_pct, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=round(win_rate, 2),
        max_drawdown=round(max_drawdown, 2),
        total_signals=strategy.metrics.total_signals,
        total_candles=len(candles),
        data_source=data_source,
        trades=trade_records,
        equity_curve=equity_curve,
        candles=candle_data,
    )
