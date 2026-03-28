"""
Trading Engine — the orchestrator for automated CPR breakout trading.

Flow:
    1. Morning scan → identify narrow CPR stocks
    2. Create CPRBreakoutStrategy instances for top picks
    3. Connect WebSocket ticker → subscribe to instrument tokens
    4. Build 5-minute candles from ticks
    5. Feed candles to strategies → strategies emit signals
    6. OrderManager processes signals → risk check → place orders
    7. Monitor positions, track P&L, auto-close at EOD (15:15)

Usage:
    engine = TradingEngine(provider, risk_manager, order_manager)
    await engine.load_picks(scan_results)   # from CPR scanner
    await engine.start()                     # connects ticker, starts loop
    await engine.stop()                      # disconnects, closes positions
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Any

from app.core.order_manager import OrderManager
from app.core.risk_manager import RiskManager
from app.providers.base import BrokerProvider
from app.providers.types import (
    Candle,
    CandleInterval,
    OrderStatus,
    TickData,
    TickMode,
)
from app.services.trade_journal import TradeJournal
from app.strategies.base import StrategyState
from app.strategies.cpr_breakout import CPRBreakoutStrategy, CPRLevels, calculate_cpr

logger = logging.getLogger(__name__)


# ── Engine States ────────────────────────────────────────────────────────────


class EngineState(str, Enum):
    IDLE = "idle"               # Not started
    LOADING = "loading"         # Loading scan results / initializing
    RUNNING = "running"         # Live — processing ticks
    PAUSED = "paused"           # Temporarily paused (no signal processing)
    STOPPING = "stopping"       # Winding down, closing positions
    STOPPED = "stopped"         # Fully stopped
    ERROR = "error"             # Fatal error


# ── Candle Builder ───────────────────────────────────────────────────────────


@dataclass
class CandleBuilder:
    """
    Aggregates ticks into 5-minute candles for a single instrument.

    A candle is "completed" when the first tick of the NEXT 5-min window
    arrives. The completed candle is returned and a new one starts.
    """

    instrument_token: int
    interval_minutes: int = 5

    # Current building candle
    _open: float = 0.0
    _high: float = 0.0
    _low: float = float("inf")
    _close: float = 0.0
    _volume: int = 0
    _window_start: datetime | None = None
    _tick_count: int = 0

    def _get_window_start(self, ts: datetime) -> datetime:
        """Round timestamp down to the nearest interval boundary."""
        minute = (ts.minute // self.interval_minutes) * self.interval_minutes
        return ts.replace(minute=minute, second=0, microsecond=0)

    def on_tick(self, tick: TickData) -> Candle | None:
        """
        Process a tick. Returns a completed Candle if interval boundary crossed,
        or None if still accumulating.
        """
        ts = tick.timestamp or datetime.now()
        price = tick.last_price
        volume = tick.volume

        if price <= 0:
            return None

        window_start = self._get_window_start(ts)

        # First tick ever
        if self._window_start is None:
            self._start_new_candle(window_start, price, volume)
            return None

        # Same window — update OHLCV
        if window_start == self._window_start:
            self._high = max(self._high, price)
            self._low = min(self._low, price)
            self._close = price
            self._volume = volume  # KiteTicker sends cumulative volume
            self._tick_count += 1
            return None

        # New window — complete previous candle and start new one
        completed = Candle(
            timestamp=self._window_start,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
        )

        self._start_new_candle(window_start, price, volume)
        return completed

    def _start_new_candle(self, window_start: datetime, price: float, volume: int) -> None:
        self._window_start = window_start
        self._open = price
        self._high = price
        self._low = price
        self._close = price
        self._volume = volume
        self._tick_count = 1

    def force_complete(self) -> Candle | None:
        """Force-complete the current candle (used at EOD)."""
        if self._window_start is None or self._tick_count == 0:
            return None
        candle = Candle(
            timestamp=self._window_start,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
        )
        self._window_start = None
        self._tick_count = 0
        return candle


# ── Stock Pick ───────────────────────────────────────────────────────────────


@dataclass
class StockPick:
    """A stock selected by the CPR scanner for today's trading."""

    trading_symbol: str
    instrument_token: int
    exchange: str
    cpr: CPRLevels
    direction: str  # "LONG", "SHORT", "WAIT"
    today_open: float
    prev_close: float
    quantity: int = 1  # Shares to trade


# ── Engine Events ────────────────────────────────────────────────────────────


@dataclass
class EngineEvent:
    """An event logged by the engine for the UI event feed."""

    timestamp: datetime
    event_type: str  # "scan", "signal", "order", "fill", "exit", "error", "info"
    message: str
    data: dict[str, Any] = field(default_factory=dict)


# ── Trading Engine ───────────────────────────────────────────────────────────


class TradingEngine:
    """
    Orchestrates the full CPR breakout trading loop.

    Lifecycle:
        1. load_picks() — accept scanner output, create strategies
        2. start() — connect ticker, begin processing
        3. (ticks arrive) → candle builder → strategy → signals → orders
        4. stop() — close positions, disconnect ticker
    """

    # EOD auto-close time (15:15 IST — 15 min before market close)
    EOD_CLOSE_TIME = time(15, 15)
    # Market close time
    MARKET_CLOSE_TIME = time(15, 30)

    def __init__(
        self,
        provider: BrokerProvider,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        journal: TradeJournal | None = None,
    ):
        self._provider = provider
        self._risk = risk_manager
        self._order_mgr = order_manager
        self._journal = journal

        # State
        self.state = EngineState.IDLE
        self._picks: list[StockPick] = []
        self._strategies: dict[int, CPRBreakoutStrategy] = {}  # token → strategy
        self._candle_builders: dict[int, CandleBuilder] = {}   # token → builder
        self._ticker = None  # TickerConnection
        self._eod_task: asyncio.Task | None = None
        self._signal_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

        # Journal: maps strategy_id → active trade_id for entry/exit tracking
        self._active_trades: dict[str, str] = {}

        # WebSocket broadcast callbacks (set by deps.py to push to ConnectionManager)
        self._on_event_cb: Any = None       # async fn(event_dict) → broadcasts engine events
        self._on_tick_cb: Any = None         # async fn(token, tick_dict) → broadcasts tick data
        self._on_status_cb: Any = None       # async fn(status_dict) → broadcasts status snapshot
        self._on_data_cb: Any = None         # async fn(type, data) → broadcasts typed data (orders, positions, risk)

        # Event loop reference (saved on start() for thread-safe tick scheduling)
        self._loop: asyncio.AbstractEventLoop | None = None

        # Metrics
        self._events: list[EngineEvent] = []
        self._total_signals: int = 0
        self._total_orders: int = 0
        self._total_fills: int = 0
        self._session_pnl: float = 0.0
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None

    # ── Public API ───────────────────────────────────────────────────────

    def load_picks(self, picks: list[StockPick]) -> None:
        """
        Load scanner results and create strategy instances.

        Each pick gets its own CPRBreakoutStrategy with pre-computed CPR
        from the scanner (no need to re-calculate from candles).
        """
        if self.state not in (EngineState.IDLE, EngineState.STOPPED):
            raise RuntimeError(f"Cannot load picks in state {self.state.value}")

        self.state = EngineState.LOADING
        self._picks = list(picks)
        self._strategies.clear()
        self._candle_builders.clear()

        for pick in picks:
            # Create strategy instance
            strategy = CPRBreakoutStrategy(
                strategy_id=f"cpr_{pick.trading_symbol}_{pick.instrument_token}",
                params={
                    "instrument_token": pick.instrument_token,
                    "trading_symbol": pick.trading_symbol,
                    "exchange": pick.exchange,
                    "quantity": pick.quantity,
                    "narrow_threshold": pick.cpr.width_pct + 0.01,  # Ensure it passes the threshold
                    "risk_reward_ratio": 2.0,
                },
            )

            # Pre-inject CPR so strategy doesn't need previous day candles
            strategy._cpr = pick.cpr
            strategy._current_day = datetime.now().strftime("%Y-%m-%d")
            strategy._traded_today = False

            self._strategies[pick.instrument_token] = strategy
            self._candle_builders[pick.instrument_token] = CandleBuilder(
                instrument_token=pick.instrument_token,
            )

        self._log_event("info", f"Loaded {len(picks)} picks for trading", {
            "symbols": [p.trading_symbol for p in picks],
        })
        self.state = EngineState.IDLE
        self._broadcast_status()
        logger.info("Loaded %d picks into trading engine", len(picks))

    async def start(self) -> None:
        """Start the trading engine — connect ticker and begin processing."""
        if self.state not in (EngineState.IDLE, EngineState.STOPPED):
            raise RuntimeError(f"Cannot start engine in state {self.state.value}")

        if not self._strategies:
            raise RuntimeError("No picks loaded. Call load_picks() first.")

        self.state = EngineState.RUNNING
        self._started_at = datetime.now()
        self._stopped_at = None

        # Save event loop for thread-safe scheduling from KiteTicker thread
        self._loop = asyncio.get_running_loop()

        # Start all strategies
        for strategy in self._strategies.values():
            await strategy.start()

        # Connect WebSocket ticker
        try:
            self._ticker = self._provider.create_ticker()
            self._ticker.set_on_tick(self._on_ticks)
            self._ticker.set_on_connect(self._on_ticker_connected)
            self._ticker.set_on_disconnect(self._on_ticker_disconnected)
            self._ticker.set_on_error(self._on_ticker_error)
            self._ticker.set_on_order_update(self._on_order_update)
            self._ticker.connect()
        except Exception as e:
            logger.warning("Ticker connection failed (will process via polling): %s", e)
            self._ticker = None
            self._log_event("info", f"Running without live ticker: {e}")

        # Start EOD auto-close task
        self._eod_task = asyncio.create_task(self._eod_close_loop())

        # Start signal processing loop
        self._signal_task = asyncio.create_task(self._signal_processing_loop())

        # Start periodic status heartbeat (5s) so UI stays fresh
        self._heartbeat_task = asyncio.create_task(self._status_heartbeat_loop())

        self._log_event("info", "Trading engine started", {
            "strategies": len(self._strategies),
            "tokens": list(self._strategies.keys()),
        })
        self._broadcast_status()
        logger.info("Trading engine started with %d strategies", len(self._strategies))

    async def stop(self, close_positions: bool = True) -> None:
        """Stop the engine — optionally close all open positions first."""
        if self.state in (EngineState.STOPPED, EngineState.IDLE):
            return

        self.state = EngineState.STOPPING
        self._log_event("info", "Stopping trading engine...")

        # Cancel background tasks
        if self._eod_task and not self._eod_task.done():
            self._eod_task.cancel()
            try:
                await self._eod_task
            except asyncio.CancelledError:
                pass

        if self._signal_task and not self._signal_task.done():
            self._signal_task.cancel()
            try:
                await self._signal_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        # Force-complete all candle builders and feed final candles
        for token, builder in self._candle_builders.items():
            candle = builder.force_complete()
            if candle and token in self._strategies:
                try:
                    await self._strategies[token].on_candle(token, candle)
                except Exception as e:
                    logger.error("Error on final candle for %d: %s", token, e)

        # Process any remaining signals
        await self._process_all_signals()

        # Stop all strategies
        for strategy in self._strategies.values():
            try:
                await strategy.stop()
            except Exception as e:
                logger.error("Error stopping strategy %s: %s", strategy.strategy_id, e)

        # Disconnect ticker
        if self._ticker:
            try:
                self._ticker.disconnect()
            except Exception as e:
                logger.error("Error disconnecting ticker: %s", e)
            self._ticker = None

        # Close any still-open journal trades (safety net for unprocessed exits)
        if self._journal and self._active_trades:
            for sid, trade_id in list(self._active_trades.items()):
                try:
                    strategy = next(
                        (s for s in self._strategies.values() if s.strategy_id == sid),
                        None,
                    )
                    # Use the strategy's last known entry price as fallback exit
                    exit_price = strategy._entry_price if strategy and strategy._entry_price else 0.0
                    trade = self._journal.record_exit(
                        trade_id=trade_id,
                        exit_price=exit_price,
                        exit_reason="engine_stop",
                    )
                    if trade:
                        self._session_pnl += trade.pnl
                        logger.info(
                            "Journal: closed orphan trade %s on engine stop, pnl=%.2f",
                            trade_id, trade.pnl,
                        )
                except Exception as e:
                    logger.error("Journal close orphan trade %s failed: %s", trade_id, e)
            self._active_trades.clear()

        self.state = EngineState.STOPPED
        self._stopped_at = datetime.now()
        self._log_event("info", "Trading engine stopped", {
            "total_signals": self._total_signals,
            "total_orders": self._total_orders,
            "session_pnl": self._session_pnl,
        })
        self._broadcast_status()
        logger.info("Trading engine stopped")

    def pause(self) -> None:
        """Pause signal processing (ticks still accumulate candles)."""
        if self.state != EngineState.RUNNING:
            return
        self.state = EngineState.PAUSED
        for strategy in self._strategies.values():
            strategy.pause()
        self._log_event("info", "Engine paused")
        self._broadcast_status()

    def resume(self) -> None:
        """Resume signal processing."""
        if self.state != EngineState.PAUSED:
            return
        self.state = EngineState.RUNNING
        for strategy in self._strategies.values():
            strategy.resume()
        self._log_event("info", "Engine resumed")
        self._broadcast_status()

    # ── Tick Processing ──────────────────────────────────────────────────

    def _on_ticks(self, ticks: list[TickData]) -> None:
        """
        Callback from KiteTicker — runs in ticker thread.
        Schedules async processing on the main event loop using
        thread-safe call_soon_threadsafe.
        """
        if not self._loop or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(
                asyncio.ensure_future,
                self._process_ticks(ticks),
            )
        except RuntimeError:
            # Loop is closed or shutting down
            pass

    async def _process_ticks(self, ticks: list[TickData]) -> None:
        """Process incoming ticks — feed to strategies for SL/target, build candles, broadcast to WebSocket."""
        if self.state not in (EngineState.RUNNING, EngineState.PAUSED):
            return

        for tick in ticks:
            token = tick.instrument_token

            # Broadcast tick to WebSocket clients
            if self._on_tick_cb:
                tick_dict = {
                    "instrument_token": token,
                    "last_price": tick.last_price,
                    "volume": tick.volume,
                    "timestamp": tick.timestamp.isoformat() if tick.timestamp else None,
                }
                try:
                    await self._on_tick_cb(token, tick_dict)
                except Exception:
                    pass  # Don't let broadcast errors affect tick processing

            builder = self._candle_builders.get(token)
            if not builder:
                continue

            # Feed every tick to strategy for real-time SL/target/trailing SL
            if self.state == EngineState.RUNNING:
                strategy = self._strategies.get(token)
                if strategy and strategy.state == StrategyState.RUNNING:
                    try:
                        await strategy.on_tick(tick)
                    except Exception as e:
                        logger.error("Strategy on_tick error (token=%d): %s", token, e)

            completed_candle = builder.on_tick(tick)
            if completed_candle is None:
                continue

            # Only feed candles to strategies when running (not paused)
            if self.state != EngineState.RUNNING:
                continue

            strategy = self._strategies.get(token)
            if not strategy or strategy.state != StrategyState.RUNNING:
                continue

            try:
                await strategy.on_candle(token, completed_candle)
            except Exception as e:
                logger.error("Strategy error on candle (token=%d): %s", token, e)
                self._log_event("error", f"Strategy error: {e}", {"token": token})

    async def feed_candle(self, instrument_token: int, candle: Candle) -> None:
        """
        Manually feed a candle to a strategy (for testing or REST-based polling).

        This bypasses the tick → candle builder flow and directly feeds
        a pre-built candle.
        """
        if self.state != EngineState.RUNNING:
            return

        strategy = self._strategies.get(instrument_token)
        if not strategy or strategy.state != StrategyState.RUNNING:
            return

        try:
            await strategy.on_candle(instrument_token, candle)
        except Exception as e:
            logger.error("Strategy error on fed candle (token=%d): %s", instrument_token, e)

    # ── Signal Processing ────────────────────────────────────────────────

    async def _signal_processing_loop(self) -> None:
        """
        Background loop that periodically drains signals from strategies
        and processes them through the order manager.
        """
        try:
            while self.state in (EngineState.RUNNING, EngineState.PAUSED):
                if self.state == EngineState.RUNNING:
                    await self._process_all_signals()
                await asyncio.sleep(1)  # Check every second
        except asyncio.CancelledError:
            # Final drain before exit
            await self._process_all_signals()

    async def _process_all_signals(self) -> None:
        """
        Drain signals from all strategies via OrderManager.

        OrderManager.process_signals() calls strategy.consume_signals()
        internally. We peek at strategy._signals first to avoid unnecessary
        calls, then log each result.

        Also records entries/exits in the trade journal for performance tracking.
        """
        had_signals = False

        for token, strategy in self._strategies.items():
            if strategy.state != StrategyState.RUNNING:
                continue

            # Peek — skip if no pending signals
            if not strategy._signals:
                continue

            had_signals = True

            # Capture signal details before OrderManager consumes them
            pending_signals = list(strategy._signals)
            for signal in pending_signals:
                self._total_signals += 1
                self._log_event("signal", (
                    f"{signal.action} {signal.trading_symbol} — {signal.reason}"
                ), {
                    "action": signal.action,
                    "symbol": signal.trading_symbol,
                    "token": signal.instrument_token,
                    "metadata": signal.metadata,
                })

            try:
                managed_orders = await self._order_mgr.process_signals(strategy)
                for i, mo in enumerate(managed_orders):
                    self._total_orders += 1
                    status = "placed" if mo.order_id else "rejected"
                    self._log_event("order", (
                        f"Order {status}: {mo.signal.action} {mo.signal.trading_symbol} "
                        f"qty={mo.request.quantity}"
                    ), {
                        "order_id": mo.order_id,
                        "status": status,
                        "error": mo.error_message,
                    })

                    # Record in journal if order was placed successfully
                    if mo.order_id and self._journal:
                        self._journal_record_order(mo, strategy)

                    # Notify strategy of order update (needed for _order_confirmed flag)
                    # For paper orders: they fill immediately during place_order()
                    # For live orders: we'll get the update via ticker callback later
                    if mo.order_id and getattr(self._provider, "is_paper", False):
                        try:
                            from app.providers.types import Order as ProviderOrder, Validity
                            order_obj = ProviderOrder(
                                order_id=mo.order_id,
                                tradingsymbol=mo.signal.trading_symbol,
                                exchange=mo.request.exchange,
                                transaction_type=mo.request.transaction_type,
                                order_type=mo.request.order_type,
                                product=mo.request.product,
                                variety=mo.request.variety,
                                status=OrderStatus.COMPLETE,
                                quantity=mo.request.quantity,
                                price=mo.request.price,
                                trigger_price=mo.request.trigger_price,
                                filled_quantity=mo.request.quantity,
                                average_price=mo.signal.metadata.get("entry_price", 0.0),
                                pending_quantity=0,
                                cancelled_quantity=0,
                                disclosed_quantity=0,
                                validity=Validity.DAY,
                                order_timestamp=mo.placed_at,
                            )
                            await strategy.on_order_update(order_obj)
                        except Exception as e:
                            logger.error("Strategy on_order_update failed: %s", e)

            except Exception as e:
                logger.error("Order processing error for %s: %s", strategy.strategy_id, e)
                self._log_event("error", f"Order error: {e}", {
                    "strategy": strategy.strategy_id,
                })

        # Broadcast updated orders/risk to WebSocket clients after processing
        if had_signals:
            self._broadcast_orders_and_risk()

    # ── Ticker Callbacks ─────────────────────────────────────────────────

    def _on_ticker_connected(self) -> None:
        """Called when WebSocket connects — subscribe to all instrument tokens."""
        tokens = list(self._strategies.keys())
        if self._ticker and tokens:
            self._ticker.subscribe(tokens, TickMode.QUOTE)
            self._log_event("info", f"Ticker connected, subscribed to {len(tokens)} instruments")
            logger.info("Ticker connected, subscribed to %d instruments", len(tokens))

    def _on_ticker_disconnected(self, code: int, reason: str | None) -> None:
        self._log_event("info", f"Ticker disconnected: code={code} reason={reason}")
        logger.warning("Ticker disconnected: code=%d reason=%s", code, reason)

    def _on_ticker_error(self, error: Exception) -> None:
        self._log_event("error", f"Ticker error: {error}")
        logger.error("Ticker error: %s", error)

    def _on_order_update(self, data: dict) -> None:
        """Handle real-time order updates from KiteTicker."""
        self._log_event("order", f"Order update: {data.get('status', 'unknown')}", data)

    # ── Status Heartbeat ───────────────────────────────────────────────

    async def _status_heartbeat_loop(self) -> None:
        """Broadcast engine status every 5 seconds so UI stays fresh."""
        try:
            while self.state in (EngineState.RUNNING, EngineState.PAUSED):
                self._broadcast_status()
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass

    # ── EOD Auto-Close ───────────────────────────────────────────────────

    async def _eod_close_loop(self) -> None:
        """Background task that auto-closes positions at EOD_CLOSE_TIME."""
        try:
            while self.state in (EngineState.RUNNING, EngineState.PAUSED):
                now = datetime.now().time()

                if now >= self.EOD_CLOSE_TIME:
                    self._log_event("info", "EOD auto-close triggered at 15:15")
                    logger.info("EOD auto-close triggered")
                    await self.stop(close_positions=True)
                    return

                # Sleep until close to EOD, checking every 30 seconds
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            pass

    # ── Status & Metrics ─────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return engine status for the UI."""
        strategy_states = {}
        for token, strategy in self._strategies.items():
            pick = next((p for p in self._picks if p.instrument_token == token), None)
            strategy_states[token] = {
                "strategy_id": strategy.strategy_id,
                "symbol": pick.trading_symbol if pick else "unknown",
                "state": strategy.state.value,
                "direction": pick.direction if pick else "unknown",
                "cpr": {
                    "pivot": pick.cpr.pivot if pick else 0,
                    "tc": pick.cpr.tc if pick else 0,
                    "bc": pick.cpr.bc if pick else 0,
                    "width_pct": pick.cpr.width_pct if pick else 0,
                } if pick else None,
                "metrics": {
                    "total_signals": strategy.metrics.total_signals,
                    "total_trades": strategy.metrics.total_trades,
                    "total_pnl": strategy.metrics.total_pnl,
                },
                "position": strategy._position,
                "entry_price": strategy._entry_price,
                "stop_loss": strategy._stop_loss,
                "target": strategy._target,
                "traded_today": strategy._traded_today,
            }

        is_paper = getattr(self._provider, "is_paper", False)
        return {
            "state": self.state.value,
            "is_paper": is_paper,
            "picks_count": len(self._picks),
            "strategies_count": len(self._strategies),
            "ticker_connected": self._ticker.is_connected() if self._ticker else False,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "stopped_at": self._stopped_at.isoformat() if self._stopped_at else None,
            "metrics": {
                "total_signals": self._total_signals,
                "total_orders": self._total_orders,
                "total_fills": self._total_fills,
                "session_pnl": self._session_pnl,
            },
            "strategies": strategy_states,
            "recent_events": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "type": e.event_type,
                    "message": e.message,
                    "data": e.data,
                }
                for e in self._events[-20:]  # Last 20 events
            ],
        }

    def get_picks(self) -> list[dict[str, Any]]:
        """Return loaded picks for the UI."""
        return [
            {
                "trading_symbol": p.trading_symbol,
                "instrument_token": p.instrument_token,
                "exchange": p.exchange,
                "direction": p.direction,
                "quantity": p.quantity,
                "today_open": p.today_open,
                "prev_close": p.prev_close,
                "cpr": {
                    "pivot": p.cpr.pivot,
                    "tc": p.cpr.tc,
                    "bc": p.cpr.bc,
                    "width": p.cpr.width,
                    "width_pct": p.cpr.width_pct,
                },
            }
            for p in self._picks
        ]

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent engine events."""
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "type": e.event_type,
                "message": e.message,
                "data": e.data,
            }
            for e in self._events[-limit:]
        ]

    # ── Internal Helpers ─────────────────────────────────────────────────

    def _journal_record_order(self, mo: Any, strategy: CPRBreakoutStrategy) -> None:
        """
        Record a successfully placed order in the trade journal.

        Determines entry vs exit based on whether the strategy already has
        an active trade in the journal:
        - No active trade → this is an entry order → record_entry()
        - Has active trade → this is an exit order → record_exit()
        """
        from app.core.order_manager import ManagedOrder

        if not self._journal:
            return

        journal = self._journal  # local for type narrowing
        sid = strategy.strategy_id
        signal = mo.signal
        metadata = signal.metadata or {}
        is_paper = getattr(self._provider, "is_paper", False)

        active_trade_id = self._active_trades.get(sid)

        if active_trade_id is None:
            # This is an ENTRY order
            trade_id = f"trade_{sid}_{mo.order_id}"

            # Determine direction from signal action
            direction = "LONG" if signal.action == "BUY" else "SHORT"

            # Get entry details from signal metadata
            entry_price = metadata.get("entry_price", 0.0)
            stop_loss = metadata.get("stop_loss", 0.0)
            target = metadata.get("target", 0.0)

            # Find the pick for exchange info
            pick = next(
                (p for p in self._picks if p.trading_symbol == signal.trading_symbol),
                None,
            )
            exchange = pick.exchange if pick else "NSE"

            try:
                journal.record_entry(
                    trade_id=trade_id,
                    order_id=mo.order_id,
                    strategy_id=sid,
                    trading_symbol=signal.trading_symbol,
                    exchange=exchange,
                    direction=direction,
                    entry_price=entry_price,
                    quantity=mo.request.quantity,
                    stop_loss=stop_loss,
                    target=target,
                    is_paper=is_paper,
                    meta=metadata,
                )
                self._active_trades[sid] = trade_id
                self._log_event("fill", (
                    f"Journal entry: {direction} {signal.trading_symbol} "
                    f"@ {entry_price:.2f} SL={stop_loss:.2f} T={target:.2f}"
                ), {"trade_id": trade_id})
            except Exception as e:
                logger.error("Journal record_entry failed: %s", e)

        else:
            # This is an EXIT order
            exit_price = metadata.get("exit_price", 0.0)
            if not exit_price:
                # Candle-based exit: entry_price in metadata is the closing candle price
                # For exits, the signal metadata has entry_price = the strategy's entry price
                # and the actual exit happens at market. Use stop_loss/target as proxy.
                exit_price = metadata.get("stop_loss", 0.0) or metadata.get("target", 0.0)

            # Determine exit reason from signal reason
            exit_reason = "manual"
            reason_lower = signal.reason.lower()
            if "stop loss" in reason_lower or "sl hit" in reason_lower:
                exit_reason = "stop_loss"
            elif "target" in reason_lower:
                exit_reason = "target"
            elif "trailing" in reason_lower:
                exit_reason = "trailing_sl"
            elif "end of day" in reason_lower or "eod" in reason_lower or "auto-close" in reason_lower:
                exit_reason = "eod_close"

            try:
                trade = journal.record_exit(
                    trade_id=active_trade_id,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                )
                del self._active_trades[sid]

                if trade:
                    self._session_pnl += trade.pnl
                    self._total_fills += 1
                    pnl_str = f"+{trade.pnl:.2f}" if trade.pnl >= 0 else f"{trade.pnl:.2f}"
                    self._log_event("exit", (
                        f"Journal exit: {trade.trading_symbol} {exit_reason} "
                        f"@ {exit_price:.2f} P&L={pnl_str}"
                    ), {
                        "trade_id": active_trade_id,
                        "pnl": trade.pnl,
                        "exit_reason": exit_reason,
                    })
            except Exception as e:
                logger.error("Journal record_exit failed: %s", e)

    def _broadcast_status(self) -> None:
        """Push a status snapshot to all engine-subscribed WebSocket clients."""
        if not self._on_status_cb:
            return
        try:
            loop = self._loop or asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._on_status_cb(self.get_status()),
                )
        except RuntimeError:
            pass  # No event loop available

    def _broadcast_data(self, data_type: str, data: Any) -> None:
        """Push typed data (orders, risk_status, etc.) to WebSocket clients."""
        if not self._on_data_cb:
            return
        try:
            loop = self._loop or asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    asyncio.ensure_future,
                    self._on_data_cb(data_type, data),
                )
        except RuntimeError:
            pass  # No event loop available

    def _broadcast_orders_and_risk(self) -> None:
        """Broadcast current orders and risk status after signal processing."""
        # Orders
        orders_data = [
            {
                "order_id": mo.order_id,
                "strategy_id": mo.strategy_id,
                "trading_symbol": mo.signal.trading_symbol,
                "action": mo.signal.action,
                "quantity": mo.request.quantity,
                "status": mo.status.value,
                "placed_at": mo.placed_at.isoformat(),
                "filled_price": mo.filled_price,
                "filled_quantity": mo.filled_quantity,
                "error_message": mo.error_message,
            }
            for mo in self._order_mgr.get_all_orders()
        ]
        self._broadcast_data("orders_update", orders_data)

        # Risk status
        risk_data = self._risk.get_status()
        self._broadcast_data("risk_update", risk_data)

    def _log_event(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        event = EngineEvent(
            timestamp=datetime.now(),
            event_type=event_type,
            message=message,
            data=data or {},
        )
        self._events.append(event)

        # Cap event history at 500
        if len(self._events) > 500:
            self._events = self._events[-500:]

        # Broadcast via WebSocket if callback is set
        if self._on_event_cb:
            event_dict = {
                "timestamp": event.timestamp.isoformat(),
                "type": event.event_type,
                "message": event.message,
                "data": event.data,
            }
            try:
                loop = self._loop or asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(
                        asyncio.ensure_future,
                        self._on_event_cb(event_dict),
                    )
            except RuntimeError:
                pass  # No event loop available
