"""
Backtest routes — run strategies against real or historical data.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ProviderDep
from app.core.backtester import run_backtest
from app.providers.types import CandleInterval

router = APIRouter(prefix="/backtest", tags=["backtest"])


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
