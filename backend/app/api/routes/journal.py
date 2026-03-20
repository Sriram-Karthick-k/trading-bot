"""
Trade journal and performance monitoring routes.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel
from fastapi import APIRouter, Query

from app.api.deps import EngineDep, get_trading_mode, get_journal as _get_journal

router = APIRouter(prefix="/journal", tags=["journal"])


# ── Request / Response Models ────────────────────────────────


class TradeEntryResponse(BaseModel):
    trade_id: str
    order_id: str
    strategy_id: str
    trading_symbol: str
    exchange: str
    direction: str
    entry_price: float
    exit_price: float | None = None
    quantity: int
    pnl: float
    pnl_pct: float
    entry_time: str | None = None
    exit_time: str | None = None
    stop_loss: float
    target: float
    exit_reason: str
    is_open: bool
    duration_minutes: float | None = None
    risk_reward_actual: float | None = None
    is_paper: bool


class DailyPnLResponse(BaseModel):
    date: str
    total_pnl: float
    realized_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    total_brokerage: float
    net_pnl: float
    is_paper: bool


class PerformanceSummaryResponse(BaseModel):
    total_trading_days: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    avg_daily_pnl: float
    best_day_pnl: float
    worst_day_pnl: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_trade_pnl: float
    avg_winner: float
    avg_loser: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    avg_trade_duration_min: float


class SessionSummaryResponse(BaseModel):
    """Current trading session summary."""
    mode: str
    is_paper: bool
    engine_state: str
    total_trades: int
    open_trades: int
    closed_trades: int
    session_pnl: float
    today_pnl: DailyPnLResponse | None
    performance: PerformanceSummaryResponse


# ── Helper to serialize ──────────────────────────────────────


def _serialize_trade(t) -> dict:
    return {
        "trade_id": t.trade_id,
        "order_id": t.order_id,
        "strategy_id": t.strategy_id,
        "trading_symbol": t.trading_symbol,
        "exchange": t.exchange,
        "direction": t.direction,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "quantity": t.quantity,
        "pnl": round(t.pnl, 2),
        "pnl_pct": round(t.pnl_pct, 2),
        "entry_time": t.entry_time.isoformat() if t.entry_time else None,
        "exit_time": t.exit_time.isoformat() if t.exit_time else None,
        "stop_loss": t.stop_loss,
        "target": t.target,
        "exit_reason": t.exit_reason,
        "is_open": not t.is_closed,
        "duration_minutes": round(t.duration_minutes, 1) if t.duration_minutes else None,
        "risk_reward_actual": round(t.risk_reward_actual, 2) if t.risk_reward_actual else None,
        "is_paper": t.is_paper,
    }


def _serialize_daily_pnl(d) -> dict:
    return {
        "date": d.date.isoformat(),
        "total_pnl": round(d.total_pnl, 2),
        "realized_pnl": round(d.realized_pnl, 2),
        "total_trades": d.total_trades,
        "winning_trades": d.winning_trades,
        "losing_trades": d.losing_trades,
        "win_rate": round(d.win_rate, 1),
        "avg_win": round(d.avg_win, 2),
        "avg_loss": round(d.avg_loss, 2),
        "largest_win": round(d.largest_win, 2),
        "largest_loss": round(d.largest_loss, 2),
        "total_brokerage": round(d.total_brokerage, 2),
        "net_pnl": round(d.net_pnl, 2),
        "is_paper": d.is_paper,
    }


def _serialize_performance(p) -> dict:
    return {
        "total_trading_days": p.total_trading_days,
        "total_trades": p.total_trades,
        "winning_trades": p.winning_trades,
        "losing_trades": p.losing_trades,
        "win_rate": round(p.win_rate, 1),
        "total_pnl": round(p.total_pnl, 2),
        "avg_daily_pnl": round(p.avg_daily_pnl, 2),
        "best_day_pnl": round(p.best_day_pnl, 2),
        "worst_day_pnl": round(p.worst_day_pnl, 2),
        "max_consecutive_wins": p.max_consecutive_wins,
        "max_consecutive_losses": p.max_consecutive_losses,
        "avg_trade_pnl": round(p.avg_trade_pnl, 2),
        "avg_winner": round(p.avg_winner, 2),
        "avg_loser": round(p.avg_loser, 2),
        "profit_factor": round(p.profit_factor, 2),
        "max_drawdown": round(p.max_drawdown, 2),
        "sharpe_ratio": round(p.sharpe_ratio, 2),
        "avg_trade_duration_min": round(p.avg_trade_duration_min, 1),
    }


# ── Singleton (delegates to deps.py) ─────────────────────────


def get_journal():
    """Get the singleton trade journal from deps."""
    return _get_journal()


def reset_journal():
    """Reset the journal (used in testing)."""
    journal = get_journal()
    journal.reset()


# ── Routes ───────────────────────────────────────────────────


@router.get("/trades")
async def get_trades(
    symbol: str | None = Query(None, description="Filter by trading symbol"),
    strategy: str | None = Query(None, description="Filter by strategy ID"),
    from_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    closed_only: bool = Query(False, description="Only show closed trades"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
):
    """Get trade journal entries with optional filters."""
    journal = get_journal()

    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date) if to_date else None

    trades = journal.get_trades(
        trading_symbol=symbol,
        strategy_id=strategy,
        from_date=fd,
        to_date=td,
        only_closed=closed_only,
    )

    return {
        "trades": [_serialize_trade(t) for t in trades[:limit]],
        "total": len(trades),
        "returned": min(len(trades), limit),
    }


@router.get("/trades/{trade_id}")
async def get_trade(trade_id: str):
    """Get a single trade entry by ID."""
    journal = get_journal()
    trades = journal.get_trades()
    trade = next((t for t in trades if t.trade_id == trade_id), None)
    if not trade:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Trade {trade_id} not found")
    return _serialize_trade(trade)


@router.get("/daily-pnl")
async def get_daily_pnl(
    from_date: str | None = Query(None, description="Start date (YYYY-MM-DD)"),
    to_date: str | None = Query(None, description="End date (YYYY-MM-DD)"),
    days: int = Query(30, ge=1, le=365, description="Number of recent days"),
):
    """Get daily P&L summaries."""
    journal = get_journal()

    fd = date.fromisoformat(from_date) if from_date else None
    td = date.fromisoformat(to_date) if to_date else None

    # If no dates specified, use last N days
    if not fd and not td:
        td = date.today()
        fd = td - __import__("datetime").timedelta(days=days)

    daily = journal.get_daily_pnl(from_date=fd, to_date=td)

    return {
        "daily_pnl": [_serialize_daily_pnl(d) for d in daily],
        "total_days": len(daily),
        "cumulative_pnl": round(sum(d.net_pnl for d in daily), 2),
    }


@router.get("/daily-pnl/today")
async def get_today_pnl():
    """Get today's P&L summary."""
    journal = get_journal()
    today = journal.get_today_pnl()
    return _serialize_daily_pnl(today)


@router.get("/performance")
async def get_performance():
    """Get overall performance metrics."""
    journal = get_journal()
    summary = journal.get_performance_summary()
    return _serialize_performance(summary)


@router.get("/session")
async def get_session_summary():
    """Get current trading session summary (combines engine + journal data)."""
    journal = get_journal()
    mode = get_trading_mode()

    # Get engine status
    try:
        from app.api.deps import get_trading_engine
        engine = get_trading_engine()
        engine_status = engine.get_status()
        engine_state = engine_status.get("state", "idle")
        session_pnl = engine_status.get("metrics", {}).get("session_pnl", 0.0)
    except Exception:
        engine_state = "idle"
        session_pnl = 0.0

    today = journal.get_today_pnl()
    performance = journal.get_performance_summary()

    return {
        "mode": mode,
        "is_paper": mode == "paper",
        "engine_state": engine_state,
        "total_trades": journal.get_trade_count(),
        "open_trades": journal.get_open_trade_count(),
        "closed_trades": journal.get_trade_count() - journal.get_open_trade_count(),
        "session_pnl": round(session_pnl, 2),
        "today_pnl": _serialize_daily_pnl(today),
        "performance": _serialize_performance(performance),
    }


@router.post("/reset")
async def reset_journal_data():
    """Reset the trade journal (clears all in-memory trade data)."""
    journal = get_journal()
    journal.reset()
    return {"status": "reset", "trades": 0}
