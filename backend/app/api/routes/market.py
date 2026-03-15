"""
Market data routes – quotes, LTP, OHLC, historical candles, instruments.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import ProviderDep
from app.providers.types import CandleInterval

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote")
async def get_quote(
    instruments: list[str] = Query(..., description="e.g. NSE:RELIANCE"),
    provider: ProviderDep = None,
):
    quotes = await provider.get_quote(instruments)
    return {
        symbol: {
            "instrument_token": q.instrument_token,
            "last_price": q.last_price,
            "ohlc_open": q.ohlc_open,
            "ohlc_high": q.ohlc_high,
            "ohlc_low": q.ohlc_low,
            "ohlc_close": q.ohlc_close,
            "volume": q.volume,
            "oi": q.oi,
            "last_quantity": q.last_quantity,
            "average_price": q.average_price,
            "buy_quantity": q.buy_quantity,
            "sell_quantity": q.sell_quantity,
            "net_change": q.net_change,
            "lower_circuit": q.lower_circuit_limit,
            "upper_circuit": q.upper_circuit_limit,
            "timestamp": q.timestamp.isoformat() if q.timestamp else None,
        }
        for symbol, q in quotes.items()
    }


@router.get("/ltp")
async def get_ltp(
    instruments: list[str] = Query(...),
    provider: ProviderDep = None,
):
    return await provider.get_ltp(instruments)


@router.get("/ohlc")
async def get_ohlc(
    instruments: list[str] = Query(...),
    provider: ProviderDep = None,
):
    ohlc = await provider.get_ohlc(instruments)
    return {
        symbol: {
            "instrument_token": q.instrument_token,
            "last_price": q.last_price,
            "ohlc_open": q.ohlc_open,
            "ohlc_high": q.ohlc_high,
            "ohlc_low": q.ohlc_low,
            "ohlc_close": q.ohlc_close,
        }
        for symbol, q in ohlc.items()
    }


@router.get("/historical/{instrument_token}")
async def get_historical(
    instrument_token: int,
    interval: str = Query(..., description="minute, 3minute, 5minute, day, etc."),
    from_date: str = Query(..., description="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"),
    to_date: str = Query(..., description="YYYY-MM-DD or YYYY-MM-DD HH:MM:SS"),
    provider: ProviderDep = None,
):
    fmt = "%Y-%m-%d %H:%M:%S" if " " in from_date else "%Y-%m-%d"
    from_dt = datetime.strptime(from_date, fmt)
    to_dt = datetime.strptime(to_date, fmt)

    candles = await provider.get_historical(
        instrument_token=instrument_token,
        interval=CandleInterval(interval),
        from_dt=from_dt,
        to_dt=to_dt,
    )
    return [
        {
            "timestamp": c.timestamp.isoformat(),
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "oi": c.oi,
        }
        for c in candles
    ]


@router.get("/instruments/search")
async def search_instruments(
    q: str = Query(..., min_length=1, description="Search query for symbol or name"),
    exchange: str | None = None,
    provider: ProviderDep = None,
):
    """Search instruments by symbol or company name."""
    instruments = await provider.get_instruments(exchange=exchange)
    query = q.upper()
    results = [
        i for i in instruments
        if query in i.tradingsymbol.upper() or query in (i.name or "").upper()
    ]
    return [
        {
            "instrument_token": i.instrument_token,
            "exchange_token": i.exchange_token,
            "trading_symbol": i.tradingsymbol,
            "name": i.name,
            "exchange": i.exchange.value,
            "instrument_type": i.instrument_type or None,
            "segment": i.segment or None,
            "lot_size": i.lot_size,
            "tick_size": i.tick_size,
            "last_price": i.last_price,
            "expiry": i.expiry.isoformat() if i.expiry else None,
            "strike": i.strike,
        }
        for i in results[:50]
    ]


@router.get("/instruments")
async def get_instruments(
    exchange: str | None = None,
    provider: ProviderDep = None,
):
    instruments = await provider.get_instruments(exchange=exchange)
    return [
        {
            "instrument_token": i.instrument_token,
            "exchange_token": i.exchange_token,
            "trading_symbol": i.tradingsymbol,
            "name": i.name,
            "exchange": i.exchange.value,
            "instrument_type": i.instrument_type or None,
            "segment": i.segment or None,
            "lot_size": i.lot_size,
            "tick_size": i.tick_size,
            "last_price": i.last_price,
            "expiry": i.expiry.isoformat() if i.expiry else None,
            "strike": i.strike,
        }
        for i in instruments[:1000]  # Limit response size
    ]
