"""
Trade Journal Service — records completed trades and provides analytics.

Works with both in-memory (current session) and DB-persisted (historical) data.
Provides daily P&L aggregation, trade statistics, and performance metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TradeEntry:
    """A completed trade (entry + exit or just entry fill)."""
    trade_id: str
    order_id: str
    strategy_id: str
    trading_symbol: str
    exchange: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    exit_price: float | None = None
    quantity: int = 0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    stop_loss: float = 0.0
    target: float = 0.0
    exit_reason: str = ""  # "target", "stop_loss", "trailing_sl", "eod_close", "manual"
    is_paper: bool = False
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def is_closed(self) -> bool:
        return self.exit_price is not None

    @property
    def duration_minutes(self) -> float | None:
        if self.entry_time and self.exit_time:
            return (self.exit_time - self.entry_time).total_seconds() / 60
        return None

    @property
    def risk_reward_actual(self) -> float | None:
        """Actual R:R achieved. Positive = profit, negative = loss."""
        if self.stop_loss and self.entry_price and self.exit_price:
            risk = abs(self.entry_price - self.stop_loss)
            if risk > 0:
                reward = abs(self.exit_price - self.entry_price)
                if self.pnl >= 0:
                    return reward / risk
                else:
                    return -(reward / risk)
        return None


@dataclass
class DailyPnL:
    """Daily P&L summary."""
    date: date
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    total_brokerage: float = 0.0
    net_pnl: float = 0.0
    is_paper: bool = False


@dataclass
class PerformanceSummary:
    """Overall performance metrics."""
    total_trading_days: int = 0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    avg_daily_pnl: float = 0.0
    best_day_pnl: float = 0.0
    worst_day_pnl: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_trade_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_trade_duration_min: float = 0.0


class TradeJournal:
    """
    In-memory trade journal for the current session.

    Records trades from the trading engine and provides analytics.
    Can be flushed to database for persistence (future enhancement).
    """

    def __init__(self) -> None:
        self._trades: dict[str, TradeEntry] = {}
        self._daily_pnl: dict[date, DailyPnL] = {}
        self._session_start: datetime = datetime.now()

    def record_entry(
        self,
        trade_id: str,
        order_id: str,
        strategy_id: str,
        trading_symbol: str,
        exchange: str,
        direction: str,
        entry_price: float,
        quantity: int,
        stop_loss: float = 0.0,
        target: float = 0.0,
        is_paper: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> TradeEntry:
        """Record a new trade entry."""
        entry = TradeEntry(
            trade_id=trade_id,
            order_id=order_id,
            strategy_id=strategy_id,
            trading_symbol=trading_symbol,
            exchange=exchange,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            target=target,
            entry_time=datetime.now(),
            is_paper=is_paper,
            meta=meta or {},
        )
        self._trades[trade_id] = entry
        logger.info(
            "Trade entry recorded: id=%s symbol=%s dir=%s price=%.2f qty=%d",
            trade_id, trading_symbol, direction, entry_price, quantity,
        )
        return entry

    def record_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str = "",
    ) -> TradeEntry | None:
        """Record a trade exit and compute P&L."""
        trade = self._trades.get(trade_id)
        if not trade:
            logger.warning("Cannot record exit: trade_id=%s not found", trade_id)
            return None

        trade.exit_price = exit_price
        trade.exit_time = datetime.now()
        trade.exit_reason = exit_reason

        # Compute P&L
        if trade.direction == "LONG":
            trade.pnl = (exit_price - trade.entry_price) * trade.quantity
        else:  # SHORT
            trade.pnl = (trade.entry_price - exit_price) * trade.quantity

        if trade.entry_price > 0:
            trade.pnl_pct = (trade.pnl / (trade.entry_price * trade.quantity)) * 100

        # Update daily P&L
        today = trade.exit_time.date()
        self._update_daily_pnl(today, trade)

        logger.info(
            "Trade exit recorded: id=%s symbol=%s pnl=%.2f reason=%s",
            trade_id, trade.trading_symbol, trade.pnl, exit_reason,
        )
        return trade

    def _update_daily_pnl(self, day: date, trade: TradeEntry) -> None:
        """Update daily P&L aggregation with a closed trade."""
        if day not in self._daily_pnl:
            self._daily_pnl[day] = DailyPnL(date=day, is_paper=trade.is_paper)

        d = self._daily_pnl[day]
        d.total_trades += 1
        d.realized_pnl += trade.pnl
        d.total_pnl = d.realized_pnl - d.total_brokerage

        if trade.pnl > 0:
            d.winning_trades += 1
            if trade.pnl > d.largest_win:
                d.largest_win = trade.pnl
        elif trade.pnl < 0:
            d.losing_trades += 1
            if trade.pnl < d.largest_loss:
                d.largest_loss = trade.pnl

        if d.total_trades > 0:
            d.win_rate = (d.winning_trades / d.total_trades) * 100

        if d.winning_trades > 0:
            winners = [t for t in self._trades.values()
                       if t.is_closed and t.exit_time and t.exit_time.date() == day and t.pnl > 0]
            d.avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0

        if d.losing_trades > 0:
            losers = [t for t in self._trades.values()
                      if t.is_closed and t.exit_time and t.exit_time.date() == day and t.pnl < 0]
            d.avg_loss = sum(t.pnl for t in losers) / len(losers) if losers else 0

        d.net_pnl = d.realized_pnl - d.total_brokerage

    def get_trades(
        self,
        trading_symbol: str | None = None,
        strategy_id: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        only_closed: bool = False,
        is_paper: bool | None = None,
    ) -> list[TradeEntry]:
        """Query trades with optional filters."""
        result = list(self._trades.values())

        if trading_symbol:
            result = [t for t in result if t.trading_symbol == trading_symbol]
        if strategy_id:
            result = [t for t in result if t.strategy_id == strategy_id]
        if from_date:
            result = [t for t in result if t.entry_time and t.entry_time.date() >= from_date]
        if to_date:
            result = [t for t in result if t.entry_time and t.entry_time.date() <= to_date]
        if only_closed:
            result = [t for t in result if t.is_closed]
        if is_paper is not None:
            result = [t for t in result if t.is_paper == is_paper]

        # Sort by entry time (newest first)
        result.sort(key=lambda t: t.entry_time or datetime.min, reverse=True)
        return result

    def get_daily_pnl(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[DailyPnL]:
        """Get daily P&L summaries for a date range."""
        result = list(self._daily_pnl.values())
        if from_date:
            result = [d for d in result if d.date >= from_date]
        if to_date:
            result = [d for d in result if d.date <= to_date]
        result.sort(key=lambda d: d.date, reverse=True)
        return result

    def get_today_pnl(self) -> DailyPnL:
        """Get today's P&L summary."""
        today = date.today()
        return self._daily_pnl.get(today, DailyPnL(date=today))

    def get_performance_summary(self) -> PerformanceSummary:
        """Compute overall performance metrics from all closed trades."""
        closed = [t for t in self._trades.values() if t.is_closed]
        if not closed:
            return PerformanceSummary()

        winners = [t for t in closed if t.pnl > 0]
        losers = [t for t in closed if t.pnl < 0]

        total_pnl = sum(t.pnl for t in closed)
        gross_profit = sum(t.pnl for t in winners) if winners else 0
        gross_loss = abs(sum(t.pnl for t in losers)) if losers else 0

        # Consecutive wins/losses
        max_consec_wins = 0
        max_consec_losses = 0
        current_wins = 0
        current_losses = 0
        sorted_trades = sorted(closed, key=lambda t: t.exit_time or datetime.min)
        for t in sorted_trades:
            if t.pnl > 0:
                current_wins += 1
                current_losses = 0
                max_consec_wins = max(max_consec_wins, current_wins)
            elif t.pnl < 0:
                current_losses += 1
                current_wins = 0
                max_consec_losses = max(max_consec_losses, current_losses)
            else:
                current_wins = 0
                current_losses = 0

        # Max drawdown (from equity curve)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sorted_trades:
            equity += t.pnl
            peak = max(peak, equity)
            dd = peak - equity
            max_dd = max(max_dd, dd)

        # Average trade duration
        durations = [t.duration_minutes for t in closed if t.duration_minutes is not None]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Daily returns for Sharpe
        daily_returns = [d.net_pnl for d in self._daily_pnl.values()]
        sharpe = 0.0
        if len(daily_returns) > 1:
            import statistics
            mean_ret = statistics.mean(daily_returns)
            std_ret = statistics.stdev(daily_returns)
            if std_ret > 0:
                sharpe = (mean_ret / std_ret) * (252 ** 0.5)  # Annualized

        daily_pnls = [d.net_pnl for d in self._daily_pnl.values()]

        return PerformanceSummary(
            total_trading_days=len(self._daily_pnl),
            total_trades=len(closed),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=(len(winners) / len(closed) * 100) if closed else 0,
            total_pnl=total_pnl,
            avg_daily_pnl=total_pnl / len(self._daily_pnl) if self._daily_pnl else 0,
            best_day_pnl=max(daily_pnls) if daily_pnls else 0,
            worst_day_pnl=min(daily_pnls) if daily_pnls else 0,
            max_consecutive_wins=max_consec_wins,
            max_consecutive_losses=max_consec_losses,
            avg_trade_pnl=total_pnl / len(closed) if closed else 0,
            avg_winner=gross_profit / len(winners) if winners else 0,
            avg_loser=-(gross_loss / len(losers)) if losers else 0,
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0,
            max_drawdown=max_dd,
            sharpe_ratio=sharpe,
            avg_trade_duration_min=avg_duration,
        )

    def get_trade_count(self) -> int:
        return len(self._trades)

    def get_open_trade_count(self) -> int:
        return sum(1 for t in self._trades.values() if not t.is_closed)

    def reset(self) -> None:
        """Clear all journal data (used for paper trading reset)."""
        self._trades.clear()
        self._daily_pnl.clear()
        self._session_start = datetime.now()
        logger.info("Trade journal reset")
