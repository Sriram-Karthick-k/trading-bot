"""
Tests for Trading Engine API endpoints.

Covers:
  - GET  /engine/status      — engine status
  - POST /engine/load-picks  — load scanner results
  - POST /engine/start       — start engine
  - POST /engine/stop        — stop engine
  - POST /engine/pause       — pause signal processing
  - POST /engine/resume      — resume signal processing
  - GET  /engine/picks       — get loaded picks
  - GET  /engine/events      — get recent events
  - POST /engine/feed-candle — feed a candle for testing
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.core.trading_engine import EngineState, TradingEngine
from app.core.risk_manager import RiskManager, RiskLimits
from app.core.order_manager import OrderManager
from app.providers.mock.provider import MockProvider
from app.providers import registry


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clean_state():
    """Clean registry and dependency singletons between tests."""
    registry.clear_registry()
    deps._config_manager = None
    deps._risk_manager = None
    deps._order_manager = None
    deps._trading_engine = None
    deps._clock = None
    deps._strategies.clear()
    yield
    registry.clear_registry()
    deps._strategies.clear()
    deps._trading_engine = None
    app.dependency_overrides.clear()


@pytest.fixture
def mock_provider():
    """Set up a mock provider as active."""
    from app.core.clock import VirtualClock
    clock = VirtualClock(initial_time=datetime(2025, 1, 15, 10, 0, 0))
    provider = MockProvider(clock=clock)
    registry.register_provider("mock", MockProvider)
    registry.create_provider("mock", {"clock": clock})
    registry.set_active_provider("mock")
    return provider


@pytest.fixture
def client(mock_provider):
    """FastAPI test client with mock provider active."""
    return TestClient(app)


@pytest.fixture
def engine_with_picks(client):
    """Client with engine pre-loaded with picks."""
    picks = _sample_picks()
    resp = client.post("/api/engine/load-picks", json={"picks": picks})
    assert resp.status_code == 200
    return client


def _sample_picks() -> list[dict]:
    return [
        {
            "trading_symbol": "RELIANCE",
            "instrument_token": 738561,
            "exchange": "NSE",
            "direction": "LONG",
            "today_open": 2505.0,
            "prev_close": 2498.0,
            "quantity": 1,
            "cpr": {
                "pivot": 2500.0,
                "tc": 2501.88,
                "bc": 2498.12,
                "width": 3.76,
                "width_pct": 0.15,
            },
        },
        {
            "trading_symbol": "INFY",
            "instrument_token": 408065,
            "exchange": "NSE",
            "direction": "SHORT",
            "today_open": 1498.0,
            "prev_close": 1505.0,
            "quantity": 2,
            "cpr": {
                "pivot": 1500.0,
                "tc": 1501.5,
                "bc": 1498.5,
                "width": 3.0,
                "width_pct": 0.2,
            },
        },
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# GET /engine/status
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetStatus:
    def test_status_idle(self, client):
        resp = client.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "idle"
        assert data["picks_count"] == 0
        assert data["strategies_count"] == 0

    def test_status_after_load(self, engine_with_picks):
        resp = engine_with_picks.get("/api/engine/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["picks_count"] == 2
        assert data["strategies_count"] == 2
        assert "738561" in data["strategies"] or 738561 in data["strategies"]


# ═══════════════════════════════════════════════════════════════════════════════
# POST /engine/load-picks
# ═══════════════════════════════════════════════════════════════════════════════


class TestLoadPicks:
    def test_load_picks_success(self, client):
        picks = _sample_picks()
        resp = client.post("/api/engine/load-picks", json={"picks": picks})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "loaded"
        assert data["picks_count"] == 2
        assert "RELIANCE" in data["symbols"]
        assert "INFY" in data["symbols"]

    def test_load_empty_picks(self, client):
        resp = client.post("/api/engine/load-picks", json={"picks": []})
        assert resp.status_code == 200
        data = resp.json()
        assert data["picks_count"] == 0

    def test_load_picks_missing_fields(self, client):
        """Missing required fields should return 422."""
        resp = client.post("/api/engine/load-picks", json={
            "picks": [{"trading_symbol": "RELIANCE"}]
        })
        assert resp.status_code == 422

    def test_load_picks_replaces_previous(self, client):
        # Load first set
        client.post("/api/engine/load-picks", json={"picks": _sample_picks()})

        # Load new set with only 1 pick
        new_picks = [_sample_picks()[0]]
        resp = client.post("/api/engine/load-picks", json={"picks": new_picks})
        assert resp.status_code == 200
        assert resp.json()["picks_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# POST /engine/start
# ═══════════════════════════════════════════════════════════════════════════════


class TestStartEngine:
    def test_start_without_picks_fails(self, client):
        resp = client.post("/api/engine/start")
        assert resp.status_code == 409

    def test_start_success(self, engine_with_picks):
        resp = engine_with_picks.post("/api/engine/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert data["strategies"] == 2

        # Clean up — stop engine
        engine_with_picks.post("/api/engine/stop")

    def test_start_twice_fails(self, engine_with_picks):
        engine_with_picks.post("/api/engine/start")
        resp = engine_with_picks.post("/api/engine/start")
        assert resp.status_code == 409

        # Clean up
        engine_with_picks.post("/api/engine/stop")


# ═══════════════════════════════════════════════════════════════════════════════
# POST /engine/stop
# ═══════════════════════════════════════════════════════════════════════════════


class TestStopEngine:
    def test_stop_idle_ok(self, client):
        """Stopping an idle engine doesn't error."""
        resp = client.post("/api/engine/stop")
        assert resp.status_code == 200

    def test_stop_running(self, engine_with_picks):
        engine_with_picks.post("/api/engine/start")
        resp = engine_with_picks.post("/api/engine/stop")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "stopped"


# ═══════════════════════════════════════════════════════════════════════════════
# POST /engine/pause & /engine/resume
# ═══════════════════════════════════════════════════════════════════════════════


class TestPauseResume:
    def test_pause_not_running(self, client):
        resp = client.post("/api/engine/pause")
        assert resp.status_code == 409

    def test_resume_not_paused(self, client):
        resp = client.post("/api/engine/resume")
        assert resp.status_code == 409

    def test_pause_resume_cycle(self, engine_with_picks):
        engine_with_picks.post("/api/engine/start")

        resp = engine_with_picks.post("/api/engine/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        resp = engine_with_picks.post("/api/engine/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "resumed"

        engine_with_picks.post("/api/engine/stop")


# ═══════════════════════════════════════════════════════════════════════════════
# GET /engine/picks
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetPicks:
    def test_picks_empty(self, client):
        resp = client.get("/api/engine/picks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_picks_after_load(self, engine_with_picks):
        resp = engine_with_picks.get("/api/engine/picks")
        assert resp.status_code == 200
        picks = resp.json()
        assert len(picks) == 2
        assert picks[0]["trading_symbol"] == "RELIANCE"
        assert picks[0]["cpr"]["pivot"] == 2500.0
        assert picks[1]["direction"] == "SHORT"


# ═══════════════════════════════════════════════════════════════════════════════
# GET /engine/events
# ═══════════════════════════════════════════════════════════════════════════════


class TestGetEvents:
    def test_events_empty(self, client):
        resp = client.get("/api/engine/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_events_after_load(self, engine_with_picks):
        resp = engine_with_picks.get("/api/engine/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1
        assert any("Loaded" in e["message"] for e in events)

    def test_events_limit(self, engine_with_picks):
        resp = engine_with_picks.get("/api/engine/events?limit=1")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) <= 1


# ═══════════════════════════════════════════════════════════════════════════════
# POST /engine/feed-candle
# ═══════════════════════════════════════════════════════════════════════════════


class TestFeedCandle:
    def test_feed_candle_not_running(self, engine_with_picks):
        """Should 409 if engine not running."""
        resp = engine_with_picks.post("/api/engine/feed-candle", json={
            "instrument_token": 738561,
            "timestamp": "2025-01-15T09:20:00",
            "open": 2505.0,
            "high": 2510.0,
            "low": 2500.0,
            "close": 2508.0,
            "volume": 1000,
        })
        assert resp.status_code == 409

    def test_feed_candle_running(self, engine_with_picks):
        engine_with_picks.post("/api/engine/start")

        resp = engine_with_picks.post("/api/engine/feed-candle", json={
            "instrument_token": 738561,
            "timestamp": "2025-01-15T09:20:00",
            "open": 2505.0,
            "high": 2510.0,
            "low": 2500.0,
            "close": 2508.0,
            "volume": 1000,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "fed"

        engine_with_picks.post("/api/engine/stop")

    def test_feed_candle_missing_fields(self, client):
        resp = client.post("/api/engine/feed-candle", json={
            "instrument_token": 738561,
        })
        assert resp.status_code == 422
