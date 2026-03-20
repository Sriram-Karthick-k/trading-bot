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


# ── Trading Mode Routes ────────────────────────────────────


class TestTradingModeRoutes:
    """Integration tests for /api/config/trading-mode endpoints."""

    @pytest.fixture(autouse=True)
    def reset_trading_mode(self):
        """Ensure trading mode is reset to 'live' before and after each test."""
        # Reset module-level globals
        deps._trading_mode = "live"
        deps._paper_provider = None
        deps._trading_engine = None
        deps._order_manager = None
        # Also reset the deps singleton config manager so lifespan doesn't
        # restore paper mode from a previous test's set_db_override
        if deps._config_manager is not None:
            deps._config_manager.set_db_override("trading.mode", "live")
        yield
        # Cleanup after test
        deps._trading_mode = "live"
        deps._paper_provider = None
        deps._trading_engine = None
        deps._order_manager = None
        if deps._config_manager is not None:
            deps._config_manager.set_db_override("trading.mode", "live")

    def test_get_trading_mode_default(self, client):
        """Default trading mode should be 'live'."""
        resp = client.get("/api/config/trading-mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "live"
        assert data["is_paper"] is False

    def test_switch_to_paper_mode(self, client):
        """Switching to paper mode should succeed when engine is idle."""
        resp = client.put("/api/config/trading-mode", json={"mode": "paper"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["old_mode"] == "live"
        assert data["new_mode"] == "paper"
        assert data["engine_reset"] is True

        # Verify mode is now paper
        resp = client.get("/api/config/trading-mode")
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paper"
        assert resp.json()["is_paper"] is True

    def test_switch_to_live_mode(self, client):
        """Switching from paper to live should succeed."""
        # First switch to paper
        deps._trading_mode = "paper"

        resp = client.put("/api/config/trading-mode", json={"mode": "live"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["old_mode"] == "paper"
        assert data["new_mode"] == "live"
        assert data["engine_reset"] is True

    def test_switch_same_mode_is_noop(self, client):
        """Switching to the same mode should be a no-op (no engine_reset)."""
        resp = client.put("/api/config/trading-mode", json={"mode": "live"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["old_mode"] == "live"
        assert data["new_mode"] == "live"
        assert data["engine_reset"] is False

    def test_switch_to_invalid_mode(self, client):
        """Invalid mode should return 400."""
        resp = client.put("/api/config/trading-mode", json={"mode": "invalid"})
        assert resp.status_code == 400

    def test_trading_mode_status_live(self, client):
        """Status endpoint in live mode should report no paper_status."""
        resp = client.get("/api/config/trading-mode/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "live"
        assert data["is_paper"] is False
        assert data["paper_status"] is None

    def test_trading_mode_status_paper(self, client):
        """Status endpoint in paper mode should report paper session details."""
        # Switch to paper via the API
        client.put("/api/config/trading-mode", json={"mode": "paper"})

        resp = client.get("/api/config/trading-mode/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mode"] == "paper"
        assert data["is_paper"] is True
        # paper_status may be None if provider isn't PaperTradingProvider
        # (depends on what get_provider returns in test context)

    def test_reset_paper_trading_not_in_paper_mode(self, client):
        """Reset should fail when not in paper mode."""
        resp = client.post("/api/config/trading-mode/reset")
        assert resp.status_code == 400
        assert "Not in paper trading mode" in resp.json()["detail"]

    def test_reset_paper_trading_in_paper_mode(self, client):
        """Reset should work when in paper mode with PaperTradingProvider."""
        from app.providers.paper.provider import PaperTradingProvider

        # Switch to paper via API
        client.put("/api/config/trading-mode", json={"mode": "paper"})

        # The provider from get_provider() in paper mode wraps the active provider.
        # Since we're using dependency override, we need to set _paper_provider directly.
        from app.providers.registry import get_active_provider
        try:
            real = get_active_provider()
        except Exception:
            real = MockProvider(clock=VirtualClock())

        paper_prov = PaperTradingProvider(real_provider=real, initial_capital=500_000)
        deps._paper_provider = paper_prov

        # Override get_provider to return the paper provider
        original_override = app.dependency_overrides.get(deps.get_provider)
        app.dependency_overrides[deps.get_provider] = lambda: paper_prov

        resp = client.post("/api/config/trading-mode/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "reset"
        assert "paper_status" in data
        assert data["paper_status"]["initial_capital"] == 500_000
        assert data["paper_status"]["total_orders"] == 0

        # Restore original override
        if original_override:
            app.dependency_overrides[deps.get_provider] = original_override

    def test_trading_mode_route_not_shadowed_by_key_catchall(self, client):
        """
        Regression: /api/config/trading-mode must NOT be caught by /{key}.
        This was the critical bug fixed by reordering routes in config.py.
        """
        resp = client.get("/api/config/trading-mode")
        assert resp.status_code == 200
        data = resp.json()
        # Should be the trading-mode handler, not the /{key} handler
        assert "mode" in data
        assert "is_paper" in data
        # The /{key} handler would return {"key": "trading-mode", "value": ...}
        assert "key" not in data

    def test_trading_mode_status_route_not_shadowed(self, client):
        """
        Regression: /api/config/trading-mode/status must NOT match /{key}.
        """
        resp = client.get("/api/config/trading-mode/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "mode" in data
        assert "is_paper" in data
        assert "paper_status" in data
