"""
Trading Engine API routes.

Endpoints for controlling the automated CPR breakout trading engine:
- Load picks from scanner results
- Start/stop/pause/resume the engine
- Get engine status, events, and strategy details
"""

from __future__ import annotations

import logging
import math

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.api.deps import get_trading_engine, get_risk_manager
from app.core.trading_engine import EngineState, StockPick, TradingEngine
from app.strategies.cpr_breakout import CPRLevels
from app.services.decision_log import decision_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/engine", tags=["engine"])


# ── Request / Response Models ────────────────────────────────────────────────


class CPRData(BaseModel):
    pivot: float
    tc: float
    bc: float
    width: float
    width_pct: float


class PickInput(BaseModel):
    trading_symbol: str
    instrument_token: int
    exchange: str = "NSE"
    direction: str = "WAIT"  # LONG, SHORT, WAIT
    today_open: float = 0.0
    prev_close: float = 0.0
    quantity: int = 1
    cpr: CPRData


class LoadPicksRequest(BaseModel):
    picks: list[PickInput]


class FeedCandleRequest(BaseModel):
    instrument_token: int
    timestamp: str  # ISO format
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


# ── Helpers ──────────────────────────────────────────────────────────────────


def _compute_position_size(
    direction: str,
    today_open: float,
    tc: float,
    bc: float,
    max_loss_per_trade: float,
    min_qty: int = 1,
    max_qty: int = 5000,
) -> int:
    """
    Compute position quantity based on risk-per-trade.

    Formula: quantity = max_loss_per_trade / SL_distance

    For LONG:  entry ≈ TC, SL ≈ BC → SL_distance = TC - BC
    For SHORT: entry ≈ BC, SL ≈ TC → SL_distance = TC - BC
    For WAIT:  use CPR width as SL distance estimate

    Returns at least min_qty and at most max_qty.
    """
    sl_distance = abs(tc - bc)

    if sl_distance < 0.01:
        # CPR too narrow to compute meaningful SL distance — use a safe fallback
        # Use 1% of the entry price as SL distance
        entry = today_open if today_open > 0 else tc
        sl_distance = entry * 0.01
        if sl_distance < 0.01:
            return min_qty

    raw_qty = max_loss_per_trade / sl_distance
    qty = max(min_qty, min(max_qty, math.floor(raw_qty)))
    return qty


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/status")
async def get_engine_status():
    """Get the current state and metrics of the trading engine."""
    engine = get_trading_engine()
    return engine.get_status()


@router.post("/load-picks")
async def load_picks(body: LoadPicksRequest):
    """
    Load scanner results into the engine.

    Takes the top picks from a CPR scan and creates strategy instances
    for each one. Must be called before start().

    Position sizing is computed automatically:
      quantity = max_loss_per_trade / SL_distance
    where SL_distance is the CPR width (TC - BC).
    """
    engine = get_trading_engine()
    risk = get_risk_manager()
    max_loss = risk.limits.max_loss_per_trade  # e.g., 10000

    try:
        picks = []
        for p in body.picks:
            cpr = CPRLevels(
                pivot=p.cpr.pivot,
                tc=p.cpr.tc,
                bc=p.cpr.bc,
                width=p.cpr.width,
                width_pct=p.cpr.width_pct,
            )

            # Compute position size from risk limits
            qty = p.quantity
            if qty <= 1:
                qty = _compute_position_size(
                    direction=p.direction,
                    today_open=p.today_open,
                    tc=cpr.tc,
                    bc=cpr.bc,
                    max_loss_per_trade=max_loss,
                )
                logger.info(
                    "Position sizing for %s: direction=%s, tc=%.2f, bc=%.2f, "
                    "max_loss=%.0f → qty=%d",
                    p.trading_symbol, p.direction, cpr.tc, cpr.bc, max_loss, qty,
                )

            picks.append(StockPick(
                trading_symbol=p.trading_symbol,
                instrument_token=p.instrument_token,
                exchange=p.exchange,
                direction=p.direction,
                today_open=p.today_open,
                prev_close=p.prev_close,
                quantity=qty,
                cpr=cpr,
            ))

        engine.load_picks(picks)
        return {
            "status": "loaded",
            "picks_count": len(picks),
            "symbols": [p.trading_symbol for p in picks],
            "quantities": {p.trading_symbol: p.quantity for p in picks},
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/start")
async def start_engine():
    """
    Start the trading engine.

    Connects the WebSocket ticker, subscribes to instruments,
    and begins processing ticks → candles → signals → orders.
    Picks must be loaded first via /load-picks.
    """
    engine = get_trading_engine()

    try:
        await engine.start()
        return {
            "status": "started",
            "state": engine.state.value,
            "strategies": len(engine._strategies),
        }
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stop")
async def stop_engine():
    """Stop the trading engine and close all positions."""
    engine = get_trading_engine()

    try:
        await engine.stop(close_positions=True)
        return {
            "status": "stopped",
            "state": engine.state.value,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pause")
async def pause_engine():
    """Pause signal processing (ticks still build candles)."""
    engine = get_trading_engine()

    if engine.state != EngineState.RUNNING:
        raise HTTPException(status_code=409, detail=f"Cannot pause in state {engine.state.value}")

    engine.pause()
    return {"status": "paused", "state": engine.state.value}


@router.post("/resume")
async def resume_engine():
    """Resume signal processing after a pause."""
    engine = get_trading_engine()

    if engine.state != EngineState.PAUSED:
        raise HTTPException(status_code=409, detail=f"Cannot resume in state {engine.state.value}")

    engine.resume()
    return {"status": "resumed", "state": engine.state.value}


@router.get("/picks")
async def get_picks():
    """Get the currently loaded picks."""
    engine = get_trading_engine()
    return engine.get_picks()


@router.get("/events")
async def get_events(limit: int = 50):
    """Get recent engine events (signals, orders, errors, etc.)."""
    engine = get_trading_engine()
    return engine.get_events(limit=min(limit, 200))


@router.post("/feed-candle")
async def feed_candle(body: FeedCandleRequest):
    """
    Manually feed a candle to a strategy (for testing without WebSocket).

    Useful when the ticker isn't connected — you can poll historical
    candles via REST and feed them here.
    """
    engine = get_trading_engine()

    if engine.state != EngineState.RUNNING:
        raise HTTPException(
            status_code=409,
            detail=f"Engine not running (state={engine.state.value})",
        )

    from datetime import datetime
    from app.providers.types import Candle

    try:
        candle = Candle(
            timestamp=datetime.fromisoformat(body.timestamp),
            open=body.open,
            high=body.high,
            low=body.low,
            close=body.close,
            volume=body.volume,
        )
        await engine.feed_candle(body.instrument_token, candle)
        return {"status": "fed", "instrument_token": body.instrument_token}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Decision Log Endpoint ────────────────────────────────────────────────────


@router.get("/logs")
async def get_decision_logs(
    limit: int = 200,
    component: str | None = None,
    level: str | None = None,
    since: str | None = None,
):
    """
    Get decision log entries.

    Query params:
        limit: Max entries to return (default 200, max 1000)
        component: Filter by component (strategy, risk, order_manager, engine)
        level: Minimum level filter (debug, info, warn, error)
        since: ISO timestamp — only return entries after this time
    """
    limit = min(limit, 1000)
    entries = decision_log.get_entries(
        limit=limit,
        component=component,
        level=level,
        since=since,
    )
    return {
        "entries": entries,
        "total_buffered": decision_log.size,
        "count": len(entries),
    }


@router.delete("/logs")
async def clear_decision_logs():
    """Clear the decision log buffer."""
    cleared = decision_log.clear()
    return {"cleared": cleared}
