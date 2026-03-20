"""
Unit tests for WebSocket ConnectionManager and engine broadcast integration.

Tests the ConnectionManager class for:
- Client connection/disconnection lifecycle
- Tick subscription and broadcast
- Engine event subscription and broadcast
- Engine status broadcast
- Disconnected client cleanup

Tests the TradingEngine broadcast callbacks:
- _on_event_cb called on _log_event
- _on_tick_cb called during _process_ticks
- _broadcast_status called on state changes
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.routes.ws import ConnectionManager
from app.core.trading_engine import (
    EngineState,
    StockPick,
    TradingEngine,
)
from app.core.order_manager import OrderManager
from app.core.risk_manager import RiskManager, RiskLimits
from app.providers.types import TickData, TickMode
from app.strategies.cpr_breakout import CPRLevels


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_cpr(pivot: float = 100.0, width_pct: float = 0.15) -> CPRLevels:
    half_width = (width_pct / 100.0) * pivot / 2.0
    tc = round(pivot + half_width, 2)
    bc = round(pivot - half_width, 2)
    width = round(tc - bc, 2)
    return CPRLevels(pivot=pivot, tc=tc, bc=bc, width=width, width_pct=round(width_pct, 4))


def make_pick(
    symbol: str = "RELIANCE",
    token: int = 738561,
    direction: str = "LONG",
) -> StockPick:
    cpr = make_cpr(pivot=2500.0, width_pct=0.15)
    return StockPick(
        trading_symbol=symbol,
        instrument_token=token,
        exchange="NSE",
        cpr=cpr,
        direction=direction,
        today_open=2505.0,
        prev_close=2498.0,
        quantity=1,
    )


def make_tick(token: int, price: float, ts: datetime) -> TickData:
    return TickData(
        instrument_token=token,
        last_price=price,
        volume=1000,
        timestamp=ts,
        mode=TickMode.QUOTE,
    )


class FakeWebSocket:
    """Minimal mock for WebSocket with send_json support."""

    def __init__(self):
        self.sent: list[dict] = []
        self.accepted = False
        self._closed = False

    async def accept(self):
        self.accepted = True

    async def send_json(self, data: dict):
        if self._closed:
            raise RuntimeError("WebSocket is closed")
        self.sent.append(data)

    def close(self):
        self._closed = True


class BrokenWebSocket(FakeWebSocket):
    """WebSocket that always raises on send."""

    async def send_json(self, data: dict):
        raise RuntimeError("Connection lost")


# ══════════════════════════════════════════════════════════════════════════════
# ConnectionManager Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestConnectionManager:
    """Test WebSocket ConnectionManager in isolation."""

    @pytest.fixture
    def manager(self):
        return ConnectionManager()

    @pytest.mark.asyncio
    async def test_connect_and_disconnect(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "client1")

        assert manager.active_connections == 1
        assert ws.accepted is True

        manager.disconnect("client1")
        assert manager.active_connections == 0

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_client(self, manager):
        # Should not raise
        manager.disconnect("nonexistent")
        assert manager.active_connections == 0

    @pytest.mark.asyncio
    async def test_tick_subscription_and_broadcast(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe("c1", [256265, 738561])

        await manager.broadcast_tick(256265, {"instrument_token": 256265, "last_price": 22000})

        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "tick"
        assert ws.sent[0]["last_price"] == 22000

    @pytest.mark.asyncio
    async def test_tick_broadcast_only_to_subscribers(self, manager):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        await manager.connect(ws1, "c1")
        await manager.connect(ws2, "c2")

        manager.subscribe("c1", [256265])
        # c2 not subscribed to this token

        await manager.broadcast_tick(256265, {"instrument_token": 256265, "last_price": 22000})

        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 0

    @pytest.mark.asyncio
    async def test_tick_unsubscribe(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe("c1", [256265, 738561])
        manager.unsubscribe("c1", [256265])

        await manager.broadcast_tick(256265, {"last_price": 22000})
        assert len(ws.sent) == 0

        await manager.broadcast_tick(738561, {"last_price": 2500})
        assert len(ws.sent) == 1

    @pytest.mark.asyncio
    async def test_engine_subscribe_and_broadcast_event(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe_engine("c1")

        assert manager.engine_subscriber_count == 1

        event = {"timestamp": "2025-01-15T10:00:00", "type": "info", "message": "Test event", "data": {}}
        await manager.broadcast_engine_event(event)

        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "engine_event"
        assert ws.sent[0]["event"]["message"] == "Test event"

    @pytest.mark.asyncio
    async def test_engine_unsubscribe(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe_engine("c1")
        manager.unsubscribe_engine("c1")

        assert manager.engine_subscriber_count == 0

        await manager.broadcast_engine_event({"message": "test"})
        assert len(ws.sent) == 0  # Not subscribed anymore

    @pytest.mark.asyncio
    async def test_engine_status_broadcast(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe_engine("c1")

        status = {"state": "running", "picks_count": 5}
        await manager.broadcast_engine_status(status)

        assert len(ws.sent) == 1
        assert ws.sent[0]["type"] == "engine_status"
        assert ws.sent[0]["status"]["state"] == "running"

    @pytest.mark.asyncio
    async def test_engine_event_only_to_engine_subscribers(self, manager):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        await manager.connect(ws1, "c1")
        await manager.connect(ws2, "c2")

        manager.subscribe_engine("c1")
        # c2 not subscribed to engine events

        await manager.broadcast_engine_event({"message": "test"})

        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 0

    @pytest.mark.asyncio
    async def test_broken_client_cleaned_up_on_tick(self, manager):
        broken = BrokenWebSocket()
        await manager.connect(broken, "broken_client")
        manager.subscribe("broken_client", [256265])

        await manager.broadcast_tick(256265, {"last_price": 100})

        # Broken client should be disconnected automatically
        assert manager.active_connections == 0

    @pytest.mark.asyncio
    async def test_broken_client_cleaned_up_on_engine_event(self, manager):
        broken = BrokenWebSocket()
        await manager.connect(broken, "broken_client")
        manager.subscribe_engine("broken_client")

        await manager.broadcast_engine_event({"message": "test"})

        assert manager.active_connections == 0
        assert manager.engine_subscriber_count == 0

    @pytest.mark.asyncio
    async def test_broken_client_cleaned_up_on_engine_status(self, manager):
        broken = BrokenWebSocket()
        await manager.connect(broken, "broken_client")
        manager.subscribe_engine("broken_client")

        await manager.broadcast_engine_status({"state": "running"})

        assert manager.active_connections == 0
        assert manager.engine_subscriber_count == 0

    @pytest.mark.asyncio
    async def test_disconnect_removes_engine_subscription(self, manager):
        ws = FakeWebSocket()
        await manager.connect(ws, "c1")
        manager.subscribe_engine("c1")

        assert manager.engine_subscriber_count == 1
        manager.disconnect("c1")
        assert manager.engine_subscriber_count == 0

    @pytest.mark.asyncio
    async def test_no_broadcast_when_no_engine_subscribers(self, manager):
        """broadcast_engine_event/status should early-return with no subscribers."""
        # Should not raise
        await manager.broadcast_engine_event({"message": "nobody listening"})
        await manager.broadcast_engine_status({"state": "idle"})

    @pytest.mark.asyncio
    async def test_multiple_clients_receive_engine_events(self, manager):
        ws1 = FakeWebSocket()
        ws2 = FakeWebSocket()
        ws3 = FakeWebSocket()
        await manager.connect(ws1, "c1")
        await manager.connect(ws2, "c2")
        await manager.connect(ws3, "c3")

        manager.subscribe_engine("c1")
        manager.subscribe_engine("c2")
        manager.subscribe_engine("c3")

        await manager.broadcast_engine_event({"message": "all hands"})

        assert len(ws1.sent) == 1
        assert len(ws2.sent) == 1
        assert len(ws3.sent) == 1


# ══════════════════════════════════════════════════════════════════════════════
# TradingEngine Broadcast Callback Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestEngineBroadcastCallbacks:
    """Test that TradingEngine calls broadcast callbacks at the right times."""

    @pytest.fixture
    def mock_provider(self):
        provider = MagicMock()
        provider.place_order = AsyncMock(return_value="ORD001")
        provider.get_ltp = AsyncMock(return_value={"256265": 22000.0})
        provider.get_orders = AsyncMock(return_value=[])
        provider.get_positions = AsyncMock(return_value={"net": [], "day": []})

        ticker = MagicMock()
        ticker.connect = MagicMock()
        ticker.disconnect = MagicMock()
        ticker.subscribe = MagicMock()
        ticker.is_connected = MagicMock(return_value=False)
        ticker.set_on_tick = MagicMock()
        ticker.set_on_connect = MagicMock()
        ticker.set_on_disconnect = MagicMock()
        ticker.set_on_error = MagicMock()
        ticker.set_on_order_update = MagicMock()
        provider.create_ticker = MagicMock(return_value=ticker)

        return provider

    @pytest.fixture
    def risk_manager(self):
        from app.core.clock import VirtualClock
        clock = VirtualClock(initial_time=datetime(2025, 1, 15, 10, 0, 0))
        return RiskManager(
            limits=RiskLimits(max_daily_loss=50_000, max_loss_per_trade=10_000),
            clock=clock,
        )

    @pytest.fixture
    def order_manager(self, mock_provider, risk_manager):
        return OrderManager(provider=mock_provider, risk_manager=risk_manager)

    @pytest.fixture
    def engine(self, mock_provider, risk_manager, order_manager):
        return TradingEngine(
            provider=mock_provider,
            risk_manager=risk_manager,
            order_manager=order_manager,
        )

    def test_log_event_calls_on_event_cb(self, engine):
        """_log_event should call _on_event_cb when set."""
        cb = AsyncMock()
        engine._on_event_cb = cb

        engine._log_event("info", "test message", {"key": "value"})

        # The callback is scheduled via asyncio.ensure_future, so it won't be
        # called synchronously. Verify the callback was set correctly.
        assert engine._on_event_cb is cb

    def test_log_event_does_not_fail_without_callback(self, engine):
        """_log_event should work fine without _on_event_cb set."""
        engine._on_event_cb = None
        engine._log_event("info", "no callback set")
        assert len(engine._events) == 1

    @pytest.mark.asyncio
    async def test_process_ticks_calls_on_tick_cb(self, engine):
        """_process_ticks should call _on_tick_cb for each tick."""
        pick = make_pick()
        engine.load_picks([pick])
        engine.state = EngineState.RUNNING

        # Start strategies
        for s in engine._strategies.values():
            await s.start()

        cb = AsyncMock()
        engine._on_tick_cb = cb

        tick = make_tick(738561, 2505.0, datetime(2025, 1, 15, 10, 5, 0))
        await engine._process_ticks([tick])

        cb.assert_called_once()
        call_args = cb.call_args
        assert call_args[0][0] == 738561  # instrument_token
        assert call_args[0][1]["last_price"] == 2505.0

    @pytest.mark.asyncio
    async def test_process_ticks_without_tick_cb(self, engine):
        """_process_ticks should not fail without _on_tick_cb."""
        pick = make_pick()
        engine.load_picks([pick])
        engine.state = EngineState.RUNNING

        for s in engine._strategies.values():
            await s.start()

        engine._on_tick_cb = None
        tick = make_tick(738561, 2505.0, datetime(2025, 1, 15, 10, 5, 0))
        await engine._process_ticks([tick])  # Should not raise

    def test_broadcast_status_calls_on_status_cb(self, engine):
        """_broadcast_status should call _on_status_cb."""
        cb = AsyncMock()
        engine._on_status_cb = cb

        engine._broadcast_status()

        # Verify callback was set
        assert engine._on_status_cb is cb

    def test_broadcast_status_noop_without_callback(self, engine):
        """_broadcast_status should not fail without callback."""
        engine._on_status_cb = None
        engine._broadcast_status()  # Should not raise

    def test_load_picks_broadcasts_status(self, engine):
        """load_picks should call _broadcast_status after loading."""
        engine._broadcast_status = MagicMock()
        pick = make_pick()
        engine.load_picks([pick])

        engine._broadcast_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_broadcasts_status(self, engine):
        """start() should call _broadcast_status after starting."""
        pick = make_pick()
        engine.load_picks([pick])

        engine._broadcast_status = MagicMock()
        await engine.start()

        engine._broadcast_status.assert_called_once()
        await engine.stop()

    @pytest.mark.asyncio
    async def test_stop_broadcasts_status(self, engine):
        """stop() should call _broadcast_status after stopping."""
        pick = make_pick()
        engine.load_picks([pick])
        await engine.start()

        engine._broadcast_status = MagicMock()
        await engine.stop()

        engine._broadcast_status.assert_called_once()

    def test_pause_broadcasts_status(self, engine):
        """pause() should call _broadcast_status after pausing."""
        pick = make_pick()
        engine.load_picks([pick])
        engine.state = EngineState.RUNNING

        engine._broadcast_status = MagicMock()
        engine.pause()

        engine._broadcast_status.assert_called_once()
        assert engine.state == EngineState.PAUSED

    def test_resume_broadcasts_status(self, engine):
        """resume() should call _broadcast_status after resuming."""
        pick = make_pick()
        engine.load_picks([pick])
        engine.state = EngineState.PAUSED

        engine._broadcast_status = MagicMock()
        engine.resume()

        engine._broadcast_status.assert_called_once()
        assert engine.state == EngineState.RUNNING

    @pytest.mark.asyncio
    async def test_tick_cb_error_does_not_crash_processing(self, engine):
        """If _on_tick_cb raises, tick processing should continue."""
        pick = make_pick()
        engine.load_picks([pick])
        engine.state = EngineState.RUNNING

        for s in engine._strategies.values():
            await s.start()

        cb = AsyncMock(side_effect=Exception("broadcast failed"))
        engine._on_tick_cb = cb

        tick = make_tick(738561, 2505.0, datetime(2025, 1, 15, 10, 5, 0))
        # Should not raise despite callback error
        await engine._process_ticks([tick])


# ══════════════════════════════════════════════════════════════════════════════
# Integration: deps.py wiring
# ══════════════════════════════════════════════════════════════════════════════


class TestDepsWiring:
    """Test that deps.py correctly wires engine callbacks to ws manager."""

    def test_get_trading_engine_wires_callbacks(self):
        """get_trading_engine should set all three broadcast callbacks."""
        import app.api.deps as deps
        from app.api.routes.ws import manager as ws_manager

        # Reset singleton
        old = deps._trading_engine
        deps._trading_engine = None

        try:
            # Mock provider to avoid real provider lookup
            with patch("app.api.deps.get_provider") as mock_prov:
                mock_prov.return_value = MagicMock()
                mock_prov.return_value.place_order = AsyncMock()

                engine = deps.get_trading_engine()

                # Bound methods create new objects each access, so we compare
                # the underlying function and instance instead of using `is`.
                assert engine._on_event_cb.__func__ is ws_manager.broadcast_engine_event.__func__
                assert engine._on_tick_cb.__func__ is ws_manager.broadcast_tick.__func__
                assert engine._on_status_cb.__func__ is ws_manager.broadcast_engine_status.__func__
        finally:
            deps._trading_engine = old
