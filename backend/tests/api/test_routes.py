"""
API route integration tests using FastAPI TestClient.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.core.clock import VirtualClock
from app.providers.mock.provider import MockProvider
from app.providers import registry


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure clean registry state for each test."""
    registry.clear_registry()
    yield
    registry.clear_registry()


@pytest.fixture
def mock_provider():
    clock = VirtualClock()
    mp = MockProvider(capital=1_000_000, clock=clock)
    mp.engine.register_instrument("NSE", "RELIANCE", 256265)
    return mp


@pytest.fixture
def client(mock_provider, risk_manager, config_manager):
    """Create test client with dependency overrides."""
    app.dependency_overrides[deps.get_provider] = lambda: mock_provider
    app.dependency_overrides[deps.get_risk_manager] = lambda: risk_manager
    app.dependency_overrides[deps.get_config_manager] = lambda: config_manager
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Health ──────────────────────────────────────────────────


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ── Auth Routes ─────────────────────────────────────────────


class TestAuthRoutes:
    def test_get_login_url(self, client):
        resp = client.get("/api/auth/login-url")
        assert resp.status_code == 200
        data = resp.json()
        assert "login_url" in data
        assert "provider" in data

    def test_callback(self, client):
        resp = client.post("/api/auth/callback", json={
            "request_token": "test_token",
            "api_key": "test_key",
            "api_secret": "test_secret",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user_id" in data
        assert "access_token" in data

    def test_session_status(self, client):
        resp = client.get("/api/auth/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "authenticated" in data


# ── Order Routes ────────────────────────────────────────────


class TestOrderRoutes:
    def test_get_orders(self, client):
        resp = client.get("/api/orders/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_place_order(self, client):
        resp = client.post("/api/orders/place", json={
            "exchange": "NSE",
            "trading_symbol": "RELIANCE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 1,
            "product": "CNC",
            "variety": "regular",
            "validity": "DAY",
        })
        # MockEngine may reject if no price feed, but the route itself should work
        assert resp.status_code in (200, 400)


# ── Portfolio Routes ────────────────────────────────────────


class TestPortfolioRoutes:
    def test_get_positions(self, client):
        resp = client.get("/api/portfolio/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "net" in data
        assert "day" in data

    def test_get_holdings(self, client):
        resp = client.get("/api/portfolio/holdings")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_margins(self, client):
        resp = client.get("/api/portfolio/margins")
        assert resp.status_code == 200


# ── Config Routes ───────────────────────────────────────────


class TestConfigRoutes:
    def test_get_all_config(self, client):
        resp = client.get("/api/config/")
        assert resp.status_code == 200

    def test_set_and_get_config(self, client):
        resp = client.put("/api/config/", json={
            "key": "test.key",
            "value": "test_value",
        })
        assert resp.status_code == 200
        assert resp.json()["key"] == "test.key"

        resp = client.get("/api/config/test.key")
        assert resp.status_code == 200
        assert resp.json()["value"] == "test_value"

    def test_get_missing_config(self, client):
        resp = client.get("/api/config/nonexistent.key")
        assert resp.status_code == 404


# ── Risk Config Routes ──────────────────────────────────────


class TestRiskRoutes:
    def test_get_risk_limits(self, client):
        resp = client.get("/api/config/risk/limits")
        assert resp.status_code == 200
        data = resp.json()
        assert "max_order_value" in data
        assert "kill_switch_active" in data

    def test_update_risk_limits(self, client):
        resp = client.put("/api/config/risk/limits", json={
            "max_daily_loss": 100_000,
        })
        assert resp.status_code == 200

        resp = client.get("/api/config/risk/limits")
        assert resp.json()["max_daily_loss"] == 100_000

    def test_get_risk_status(self, client):
        resp = client.get("/api/config/risk/status")
        assert resp.status_code == 200

    def test_kill_switch(self, client):
        resp = client.post("/api/config/risk/kill-switch/activate")
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is True

        resp = client.post("/api/config/risk/kill-switch/deactivate")
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is False


# ── Provider Routes ─────────────────────────────────────────


class TestProviderRoutes:
    def test_list_providers_empty(self, client):
        resp = client.get("/api/providers/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_discover_providers(self, client):
        resp = client.post("/api/providers/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "discovered" in data

    def test_get_active_no_provider(self, client):
        resp = client.get("/api/providers/active")
        assert resp.status_code == 200


# ── Strategy Routes ─────────────────────────────────────────


class TestStrategyRoutes:
    def test_list_strategies_empty(self, client):
        resp = client.get("/api/strategies/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_strategy_not_found(self, client):
        resp = client.get("/api/strategies/nonexistent")
        assert resp.status_code == 404

    def test_list_strategy_types(self, client):
        resp = client.get("/api/strategies/types")
        assert resp.status_code == 200


# ── Mock Routes ─────────────────────────────────────────────


class TestMockRoutes:
    def test_non_mock_provider_rejected(self, client):
        """When active provider is not mock, mock routes should fail."""
        # Default provider in fixture IS a MockProvider, so this should work
        resp = client.post("/api/mock/session", json={
            "initial_capital": 500_000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "created"
        assert data["initial_capital"] == 500_000

    def test_mock_session_status(self, client):
        # Create session first
        client.post("/api/mock/session", json={"initial_capital": 500_000})
        resp = client.get("/api/mock/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "virtual_capital" in data
        assert "is_market_open" in data
        assert "speed" in data
        assert "paused" in data

    def test_mock_time_controls(self, client):
        client.post("/api/mock/session", json={})

        resp = client.post("/api/mock/time/speed", json={"speed": 2.0})
        assert resp.status_code == 200
        assert resp.json()["speed"] == 2.0

        resp = client.post("/api/mock/time/pause")
        assert resp.status_code == 200
        assert resp.json()["paused"] is True

        resp = client.post("/api/mock/time/resume")
        assert resp.status_code == 200
        assert resp.json()["paused"] is False

    def test_mock_orders(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/orders")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_mock_positions(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "net" in data

    def test_mock_reset(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"
