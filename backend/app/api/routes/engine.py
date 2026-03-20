"""
Trading Engine API routes.

Endpoints for controlling the automated CPR breakout trading engine:
- Load picks from scanner results
- Start/stop/pause/resume the engine
- Get engine status, events, and strategy details
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.api.deps import get_trading_engine
from app.core.trading_engine import EngineState, StockPick, TradingEngine
from app.strategies.cpr_breakout import CPRLevels

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
    """
    engine = get_trading_engine()

    try:
        picks = [
            StockPick(
                trading_symbol=p.trading_symbol,
                instrument_token=p.instrument_token,
                exchange=p.exchange,
                direction=p.direction,
                today_open=p.today_open,
                prev_close=p.prev_close,
                quantity=p.quantity,
                cpr=CPRLevels(
                    pivot=p.cpr.pivot,
                    tc=p.cpr.tc,
                    bc=p.cpr.bc,
                    width=p.cpr.width,
                    width_pct=p.cpr.width_pct,
                ),
            )
            for p in body.picks
        ]
        engine.load_picks(picks)
        return {
            "status": "loaded",
            "picks_count": len(picks),
            "symbols": [p.trading_symbol for p in picks],
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
