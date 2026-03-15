"""
Mock testing routes – session management, time control, replay.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ProviderDep, ClockDep
from app.core.clock import VirtualClock
from app.providers.mock.provider import MockProvider
from app.providers.types import Credentials

router = APIRouter(prefix="/mock", tags=["mock"])


class CreateMockSessionRequest(BaseModel):
    initial_capital: float = 1_000_000.0
    start_date: str | None = None  # YYYY-MM-DD
    end_date: str | None = None


class SetDateRequest(BaseModel):
    date: str  # YYYY-MM-DD


class SetSpeedRequest(BaseModel):
    speed: float


class SeekRequest(BaseModel):
    hour: int
    minute: int


def _get_mock_provider(provider) -> MockProvider:
    if not isinstance(provider, MockProvider):
        raise HTTPException(status_code=400, detail="Active provider is not a MockProvider")
    return provider


@router.post("/session")
async def create_session(body: CreateMockSessionRequest, provider: ProviderDep):
    mock = _get_mock_provider(provider)
    credentials = Credentials(api_key="mock", api_secret="mock")
    session = await mock.authenticate(credentials=credentials, request_token="mock")
    mock.engine.initial_capital = body.initial_capital
    mock.engine.available_capital = body.initial_capital
    if body.start_date:
        from datetime import datetime
        dt = datetime.strptime(body.start_date, "%Y-%m-%d")
        mock.time_controller.set_date_range(
            start=dt,
            end=datetime.strptime(body.end_date, "%Y-%m-%d") if body.end_date else dt,
        )
    return {
        "session_id": session.user_id,
        "initial_capital": body.initial_capital,
        "status": "created",
    }


@router.post("/sample-data")
async def load_sample_data(provider: ProviderDep):
    """Load sample NSE instruments with approximate prices for paper trading."""
    mock = _get_mock_provider(provider)
    result = mock.engine.load_sample_data()
    # Also populate the provider's instrument list so /market/instruments works
    mock.load_instruments(mock.engine.get_sample_as_instruments())
    return result


@router.get("/instruments")
async def get_mock_instruments(provider: ProviderDep):
    """Get available sample instruments with current LTP."""
    mock = _get_mock_provider(provider)
    return mock.engine.get_sample_instruments()


@router.get("/session")
async def get_session_status(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    engine = mock.engine
    tc = mock.time_controller
    return {
        "virtual_capital": engine.available_capital,
        "current_time": tc.clock.now().isoformat(),
        "is_market_open": tc.is_market_hours(),
        "progress": tc.get_progress(),
        "speed": tc.clock.get_speed() if isinstance(tc.clock, VirtualClock) else 1.0,
        "paused": tc.clock.is_paused() if isinstance(tc.clock, VirtualClock) else False,
        "open_orders": len([o for o in engine._orders.values() if o.status.value in ("PENDING", "OPEN")]),
        "positions": len(engine._positions),
        "total_pnl": engine.realized_pnl + engine.unrealized_pnl,
    }


@router.post("/time/set-date")
async def set_date(body: SetDateRequest, provider: ProviderDep):
    mock = _get_mock_provider(provider)
    from datetime import datetime
    dt = datetime.strptime(body.date, "%Y-%m-%d")
    mock.time_controller.set_date_range(start=dt, end=dt)
    return {"date": body.date, "time": mock.time_controller.clock.now().isoformat()}


@router.post("/time/market-open")
async def advance_to_market_open(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.advance_to_market_open()
    return {"time": mock.time_controller.clock.now().isoformat()}


@router.post("/time/market-close")
async def advance_to_market_close(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.advance_to_market_close()
    return {"time": mock.time_controller.clock.now().isoformat()}


@router.post("/time/next-day")
async def advance_to_next_day(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.advance_to_next_trading_day()
    return {"time": mock.time_controller.clock.now().isoformat()}


@router.post("/time/speed")
async def set_speed(body: SetSpeedRequest, provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.set_speed(body.speed)
    return {"speed": body.speed}


@router.post("/time/pause")
async def pause(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.pause()
    return {"paused": True}


@router.post("/time/resume")
async def resume(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.time_controller.resume()
    return {"paused": False}


@router.post("/reset")
async def reset_session(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    mock.engine.reset()
    return {"status": "reset"}


@router.get("/orders")
async def get_mock_orders(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    orders = await mock.get_orders()
    return [
        {
            "order_id": o.order_id,
            "trading_symbol": o.tradingsymbol,
            "transaction_type": o.transaction_type.value,
            "quantity": o.quantity,
            "price": o.price,
            "average_price": o.average_price,
            "status": o.status.value,
        }
        for o in orders
    ]


@router.get("/positions")
async def get_mock_positions(provider: ProviderDep):
    mock = _get_mock_provider(provider)
    positions = await mock.get_positions()
    return {
        "net": [
            {
                "trading_symbol": p.tradingsymbol,
                "quantity": p.quantity,
                "average_price": p.average_price,
                "last_price": p.last_price,
                "pnl": p.pnl,
            }
            for p in positions.net
        ]
    }
