"""
Backtest routes — run strategies against real or historical data.

Includes:
  POST /backtest/run       — Run any registered strategy against historical candles.
  POST /backtest/cpr-scan  — Scan constituent stocks of NIFTY indices for narrow CPR.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.api.deps import ProviderDep
from app.core.backtester import run_backtest, fetch_candles
from app.providers.types import CandleInterval
from app.services.nse_index import (
    NSEIndexService,
    NSEIndexError,
    AVAILABLE_INDICES,
    INDEX_URL_NAMES,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/backtest", tags=["backtest"])

# Shared NSE index service instance (lazy-initialized)
_nse_service: NSEIndexService | None = None


def _get_nse_service() -> NSEIndexService:
    """Get or create the shared NSE index service."""
    global _nse_service
    if _nse_service is None:
        _nse_service = NSEIndexService(cache_ttl_seconds=600)  # 10 min cache
    return _nse_service


class BacktestRequest(BaseModel):
    strategy_type: str
    instrument_token: int
    tradingsymbol: str
    exchange: str = "NSE"
    interval: str = "day"  # minute, 5minute, 15minute, 60minute, day
    from_date: str  # YYYY-MM-DD
    to_date: str  # YYYY-MM-DD
    initial_capital: float = 100_000.0
    params: dict = {}


# Import strategy classes lazily
_STRATEGY_CLASSES: dict = {}


def _discover_strategies():
    if _STRATEGY_CLASSES:
        return
    try:
        from app.strategies.sma_crossover import SMAcrossoverStrategy
        _STRATEGY_CLASSES[SMAcrossoverStrategy.name()] = SMAcrossoverStrategy
    except ImportError:
        pass
    try:
        from app.strategies.rsi_strategy import RSIStrategy
        _STRATEGY_CLASSES[RSIStrategy.name()] = RSIStrategy
    except ImportError:
        pass
    try:
        from app.strategies.cpr_breakout import CPRBreakoutStrategy
        _STRATEGY_CLASSES[CPRBreakoutStrategy.name()] = CPRBreakoutStrategy
    except ImportError:
        pass


@router.post("/run")
async def run_backtest_endpoint(body: BacktestRequest, provider: ProviderDep):
    """
    Run a backtest: replay real historical data through a strategy.

    Uses the active provider to fetch candles — if Zerodha is authenticated,
    you get real market data. If mock is active, uses synthetic data.

    Returns complete results: trades, equity curve, P&L, drawdown.
    """
    _discover_strategies()

    # Validate strategy type
    cls = _STRATEGY_CLASSES.get(body.strategy_type)
    if not cls:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy type: '{body.strategy_type}'. "
                   f"Available: {list(_STRATEGY_CLASSES.keys())}",
        )

    # Parse dates
    try:
        from_dt = datetime.strptime(body.from_date, "%Y-%m-%d")
        to_dt = datetime.strptime(body.to_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    if from_dt >= to_dt:
        raise HTTPException(status_code=400, detail="from_date must be before to_date")

    # Validate interval
    try:
        interval = CandleInterval(body.interval)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid interval: '{body.interval}'. "
                   f"Use: minute, 5minute, 15minute, 60minute, day",
        )

    # Fill default params from schema
    schema = cls.get_params_schema()
    params = dict(body.params)
    params.setdefault("instrument_token", body.instrument_token)
    params.setdefault("trading_symbol", body.tradingsymbol)
    params.setdefault("exchange", body.exchange)
    for pdef in schema:
        if pdef.name not in params and pdef.default is not None:
            params[pdef.name] = pdef.default

    # Create strategy instance
    strategy = cls(strategy_id=f"backtest_{body.strategy_type}", params=params)
    errors = strategy.validate_params()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    # Run backtest
    result = await run_backtest(
        strategy=strategy,
        provider=provider,
        instrument_token=body.instrument_token,
        tradingsymbol=body.tradingsymbol,
        exchange=body.exchange,
        interval=interval,
        from_dt=from_dt,
        to_dt=to_dt,
        initial_capital=body.initial_capital,
    )

    return {
        "strategy": result.strategy_name,
        "symbol": result.symbol,
        "interval": result.interval,
        "from_date": result.from_date,
        "to_date": result.to_date,
        "data_source": result.data_source,
        "initial_capital": result.initial_capital,
        "final_capital": result.final_capital,
        "total_pnl": result.total_pnl,
        "total_return_pct": result.total_return_pct,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": result.win_rate,
        "max_drawdown": result.max_drawdown,
        "total_signals": result.total_signals,
        "total_candles": result.total_candles,
        "trades": [
            {
                "timestamp": t.timestamp,
                "action": t.action,
                "symbol": t.symbol,
                "quantity": t.quantity,
                "price": t.price,
                "order_id": t.order_id,
                "reason": t.reason,
            }
            for t in result.trades
        ],
        "equity_curve": result.equity_curve,
    }


# ── CPR Scanner ─────────────────────────────────────────────────────────────


# Fallback hardcoded constituents — used when NSE API is unreachable.
# These are a minimal subset of real constituents for offline/test use.
_FALLBACK_CONSTITUENTS: dict[str, list[str]] = {
    "NIFTY 50": [
        "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN",
        "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "WIPRO", "HINDUNILVR",
        "AXISBANK", "TATAMOTORS", "SUNPHARMA", "BAJFINANCE", "MARUTI",
        "TITAN", "ASIANPAINT", "HCLTECH",
    ],
    "NIFTY BANK": [
        "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK",
    ],
    "NIFTY IT": [
        "TCS", "INFY", "WIPRO", "HCLTECH",
    ],
    "NIFTY FIN SERVICE": [
        "HDFCBANK", "ICICIBANK", "SBIN", "KOTAKBANK", "AXISBANK", "BAJFINANCE",
    ],
    "NIFTY PHARMA": ["SUNPHARMA"],
    "NIFTY AUTO": ["TATAMOTORS", "MARUTI"],
    "NIFTY METAL": [],
    "NIFTY ENERGY": ["RELIANCE"],
    "NIFTY FMCG": ["ITC", "HINDUNILVR"],
    "NIFTY REALTY": [],
    "NIFTY INFRA": ["LT"],
    "NIFTY PSU BANK": ["SBIN"],
    "NIFTY MEDIA": [],
    "NIFTY MIDCAP 50": [],
    "NIFTY MIDCAP 100": [],
    "NIFTY MID SELECT": [],
}


async def _get_index_constituents(indices: list[str]) -> dict[str, list[str]]:
    """
    Fetch index constituent symbols, with fallback to hardcoded data.

    Tries the live NSE API first. If that fails (network error, rate limit,
    NSE blocking), falls back to the hardcoded subset. If NSE returns partial
    results (some indices succeed, some fail), missing indices use fallback.
    """
    nse = _get_nse_service()
    try:
        result = await nse.get_all_constituent_symbols(indices=indices)
        if result:
            # Fill in any missing indices from fallback
            for idx in indices:
                if idx not in result:
                    fallback = _FALLBACK_CONSTITUENTS.get(idx, [])
                    if fallback:
                        logger.info("Using fallback data for %s (%d stocks)", idx, len(fallback))
                    result[idx] = fallback
            logger.info("Using live NSE data for %d indices", len(result))
            return result
    except NSEIndexError as e:
        logger.warning("NSE API unavailable, using fallback data: %s", e)
    except Exception as e:
        logger.warning("Unexpected error fetching NSE data, using fallback: %s", e)

    # Fallback to hardcoded data
    logger.info("Using full fallback data for %d indices", len(indices))
    return {idx: _FALLBACK_CONSTITUENTS.get(idx, []) for idx in indices}


class CPRScanRequest(BaseModel):
    """Request model for CPR scanner — scans constituent stocks for narrow CPR."""
    scan_date: str  # YYYY-MM-DD — the trading day to scan
    indices: list[str] = Field(
        default_factory=lambda: list(AVAILABLE_INDICES),
        description="List of index names to scan. Defaults to all available.",
    )
    narrow_threshold: float = Field(
        default=0.5,
        description="CPR width % below which a stock is flagged as narrow",
    )


@router.get("/cpr-scan/indices")
async def list_available_indices():
    """
    List all available NIFTY indices for the CPR scanner.

    Attempts to fetch live constituent counts from NSE. Falls back to
    static index list with zero counts if NSE is unreachable.
    """
    nse = _get_nse_service()
    try:
        all_data = await nse.get_all_constituents()
        if all_data:
            return {
                "indices": [
                    {
                        "name": name,
                        "constituent_count": data.constituent_count,
                    }
                    for name, data in all_data.items()
                ],
                "source": "nse_live",
            }
        logger.warning("NSE returned empty data for all indices, using fallback")
    except Exception as e:
        logger.warning("NSE API error, using fallback: %s", e)

    # Fallback: return the list with hardcoded counts
    return {
        "indices": [
            {"name": name, "constituent_count": len(_FALLBACK_CONSTITUENTS.get(name, []))}
            for name in AVAILABLE_INDICES
        ],
        "source": "fallback",
    }


@router.get("/cpr-scan/cache-status")
async def get_nse_cache_status():
    """Return the current state of the NSE index data cache."""
    nse = _get_nse_service()
    return nse.get_cache_status()


@router.post("/cpr-scan")
async def cpr_scan_endpoint(body: CPRScanRequest, provider: ProviderDep):
    """
    Scan constituent stocks of selected NIFTY indices for narrow CPR.

    For a given scan_date:
    1. Gets constituent stocks for each selected index (live from NSE or fallback)
    2. Fetches the previous trading day's OHLC for each stock
    3. Calculates CPR levels (pivot, TC, BC) from previous day data
    4. Returns ALL stocks sorted by CPR width (narrowest first)

    This is a scan-and-signal endpoint — no trades are placed.
    """
    from app.strategies.cpr_breakout import calculate_cpr

    # Parse scan date
    try:
        scan_dt = datetime.strptime(body.scan_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    # Validate indices
    invalid = [i for i in body.indices if i not in INDEX_URL_NAMES]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown indices: {invalid}. Available: {AVAILABLE_INDICES}",
        )

    # Fetch constituents (live NSE or fallback)
    index_constituents = await _get_index_constituents(body.indices)

    # Collect unique stocks across selected indices, tracking which index they belong to
    stock_to_indices: dict[str, list[str]] = {}
    for idx_name in body.indices:
        for symbol in index_constituents.get(idx_name, []):
            stock_to_indices.setdefault(symbol, []).append(idx_name)

    if not stock_to_indices:
        return {
            "scan_date": body.scan_date,
            "scan_params": {
                "narrow_threshold": body.narrow_threshold,
                "indices_selected": body.indices,
                "unique_stocks": 0,
            },
            "summary": {
                "total_stocks_scanned": 0,
                "narrow_count": 0,
            },
            "stocks": [],
            "errors": [{"symbol": "N/A", "error": "No constituent stocks found for selected indices"}],
        }

    # Get all available instruments from the provider to resolve symbol → token
    try:
        instruments = await provider.get_instruments()
    except Exception:
        instruments = []

    symbol_to_token: dict[str, int] = {}
    symbol_to_name: dict[str, str] = {}
    for inst in instruments:
        sym = inst.tradingsymbol.upper()
        if sym not in symbol_to_token:
            symbol_to_token[sym] = inst.instrument_token
            symbol_to_name[sym] = inst.name or sym

    # Need to fetch candles covering the previous trading day.
    # Go back 10 days to be safe (weekends + holidays).
    # Use end-of-day for to_dt so candles ON scan_date are included
    # (candle timestamps use 09:15 which is after midnight).
    from_dt = scan_dt - timedelta(days=10)
    to_dt = scan_dt.replace(hour=23, minute=59, second=59)

    results: list[dict] = []
    errors: list[dict] = []

    for symbol, indices in stock_to_indices.items():
        token = symbol_to_token.get(symbol.upper())
        if token is None:
            errors.append({
                "symbol": symbol,
                "error": f"Instrument token not found (stock may not be loaded)",
            })
            continue

        try:
            candles, data_source = await fetch_candles(
                provider=provider,
                instrument_token=token,
                interval=CandleInterval.DAY,
                from_dt=from_dt,
                to_dt=to_dt,
            )

            if len(candles) < 2:
                errors.append({
                    "symbol": symbol,
                    "error": "Insufficient daily data (need >= 2 candles)",
                })
                continue

            # Find the candle on or just before scan_date (today) and the one before it (prev day)
            # Candles are sorted by timestamp ascending
            scan_date_str = body.scan_date

            # Filter candles up to and including scan_date
            relevant = [c for c in candles if c.timestamp.strftime("%Y-%m-%d") <= scan_date_str]

            if len(relevant) < 2:
                errors.append({
                    "symbol": symbol,
                    "error": "Not enough trading days before scan date",
                })
                continue

            # Determine if scan_date itself has a candle
            last_candle = relevant[-1]
            last_candle_date = last_candle.timestamp.strftime("%Y-%m-%d")

            if last_candle_date == scan_date_str:
                # Scan date has data: prev_day is second-to-last, today is last
                prev_candle = relevant[-2]
                today_candle = last_candle
                today_open = round(today_candle.open, 2)
            else:
                # Scan date has no candle yet (before market open, holiday, future)
                # Use last candle as "prev_day" to calculate CPR for scan_date
                # today_open is unknown — use prev close as proxy
                prev_candle = relevant[-1]
                today_candle = prev_candle  # use prev day for scan_date field
                today_open = round(prev_candle.close, 2)

            cpr = calculate_cpr(prev_candle.high, prev_candle.low, prev_candle.close)

            results.append({
                "symbol": symbol,
                "name": symbol_to_name.get(symbol.upper(), symbol),
                "instrument_token": token,
                "indices": indices,
                "scan_date": scan_date_str,
                "prev_day": {
                    "date": prev_candle.timestamp.strftime("%Y-%m-%d"),
                    "open": round(prev_candle.open, 2),
                    "high": round(prev_candle.high, 2),
                    "low": round(prev_candle.low, 2),
                    "close": round(prev_candle.close, 2),
                },
                "cpr": {
                    "pivot": round(cpr.pivot, 2),
                    "tc": round(cpr.tc, 2),
                    "bc": round(cpr.bc, 2),
                    "width": round(cpr.width, 2),
                    "width_pct": round(cpr.width_pct, 4),
                    "is_narrow": cpr.width_pct < body.narrow_threshold,
                },
                "today_open": today_open,
                "data_source": data_source,
            })
        except Exception as e:
            logger.warning("CPR scan failed for %s (token=%s): %s", symbol, token, e)
            errors.append({"symbol": symbol, "error": str(e)})

    # Sort by width_pct ascending (narrowest first)
    results.sort(key=lambda r: r["cpr"]["width_pct"])

    narrow_count = sum(1 for r in results if r["cpr"]["is_narrow"])

    return {
        "scan_date": body.scan_date,
        "scan_params": {
            "narrow_threshold": body.narrow_threshold,
            "indices_selected": body.indices,
            "unique_stocks": len(stock_to_indices),
        },
        "summary": {
            "total_stocks_scanned": len(results),
            "narrow_count": narrow_count,
        },
        "stocks": results,
        "errors": errors if errors else None,
    }
