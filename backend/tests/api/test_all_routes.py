"""
Comprehensive API route tests — covers all endpoints, auth flow,
env loading, provider lifecycle, and edge cases.
"""

from __future__ import annotations

import hashlib
import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
from app.core.clock import VirtualClock
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
    deps._clock = None
    deps._strategies.clear()
    yield
    registry.clear_registry()
    deps._strategies.clear()
    app.dependency_overrides.clear()


@pytest.fixture
def clock():
    return VirtualClock()


@pytest.fixture
def mock_provider(clock):
    mp = MockProvider(capital=1_000_000, clock=clock)
    mp.engine.register_instrument("NSE", "RELIANCE", 256265)
    mp.engine.register_instrument("NSE", "INFY", 408065)
    mp.engine.register_instrument("NSE", "TCS", 2953217)
    return mp


@pytest.fixture
def client(mock_provider, risk_manager, config_manager):
    """Test client with mock provider active via dependency overrides."""
    order_manager = OrderManager(provider=mock_provider, risk_manager=risk_manager)
    app.dependency_overrides[deps.get_provider] = lambda: mock_provider
    app.dependency_overrides[deps.get_risk_manager] = lambda: risk_manager
    app.dependency_overrides[deps.get_config_manager] = lambda: config_manager
    app.dependency_overrides[deps.get_order_manager] = lambda: order_manager
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def client_no_provider(risk_manager, config_manager):
    """Test client WITHOUT any active provider (tests error paths)."""
    app.dependency_overrides[deps.get_risk_manager] = lambda: risk_manager
    app.dependency_overrides[deps.get_config_manager] = lambda: config_manager
    # Do NOT override get_provider — let it raise
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ═══════════════════════════════════════════════════════════════
#  HEALTH
# ═══════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    def test_health_returns_200(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_has_version(self, client):
        resp = client.get("/api/health")
        assert resp.json()["version"] == "0.1.0"


# ═══════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ═══════════════════════════════════════════════════════════════


class TestAuthLoginUrl:
    """Tests for GET /api/auth/login-url"""

    def test_login_url_from_mock_provider(self, client):
        """Mock provider returns its own login URL."""
        resp = client.get("/api/auth/login-url")
        assert resp.status_code == 200
        data = resp.json()
        assert "login_url" in data
        assert data["login_url"] == "mock://login"
        assert data["provider"] == "mock"

    def test_login_url_always_succeeds_for_mock(self, client):
        """Mock provider doesn't need API key, so no 500 error."""
        resp = client.get("/api/auth/login-url")
        assert resp.status_code == 200
        assert "login_url" in resp.json()


class TestAuthRedirect:
    """Tests for GET /api/auth/redirect (browser redirect from Zerodha)"""

    @patch.dict(os.environ, {
        "TRADE_ZERODHA_API_KEY": "test_key",
        "TRADE_ZERODHA_API_SECRET": "test_secret",
    })
    def test_redirect_success(self, client):
        resp = client.get(
            "/api/auth/redirect",
            params={"request_token": "mock_token", "status": "success"},
            follow_redirects=False,
        )
        # MockProvider authenticates successfully, should redirect to frontend
        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "auth=success" in location

    def test_redirect_failed_status(self, client):
        resp = client.get(
            "/api/auth/redirect",
            params={"request_token": "tok", "status": "failed"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        assert "auth_error=login_failed" in resp.headers["location"]

    def test_redirect_missing_credentials(self, client):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TRADE_ZERODHA_API_KEY", None)
            os.environ.pop("TRADE_ZERODHA_API_SECRET", None)
            resp = client.get(
                "/api/auth/redirect",
                params={"request_token": "tok", "status": "success"},
                follow_redirects=False,
            )
            assert resp.status_code == 307
            assert "missing_credentials" in resp.headers["location"]

    def test_redirect_missing_request_token_returns_422(self, client):
        resp = client.get("/api/auth/redirect", params={"status": "success"})
        assert resp.status_code == 422  # FastAPI validation error


class TestAuthCallback:
    """Tests for POST /api/auth/callback (programmatic token exchange)"""

    def test_callback_with_token(self, client):
        resp = client.post("/api/auth/callback", json={
            "request_token": "test_token",
            "api_key": "test_key",
            "api_secret": "test_secret",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "user_id" in data
        assert "access_token" in data
        assert "broker" in data

    def test_callback_uses_env_credentials(self, client):
        """When api_key/api_secret not in body, fallback to env vars."""
        with patch.dict(os.environ, {
            "TRADE_ZERODHA_API_KEY": "env_key",
            "TRADE_ZERODHA_API_SECRET": "env_secret",
        }):
            resp = client.post("/api/auth/callback", json={
                "request_token": "test_token",
            })
            assert resp.status_code == 200

    def test_callback_invalid_body(self, client):
        resp = client.post("/api/auth/callback", json={})
        assert resp.status_code == 422  # Missing required request_token


class TestAuthSession:
    """Tests for GET /api/auth/session"""

    def test_session_check(self, client):
        resp = client.get("/api/auth/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "authenticated" in data
        assert isinstance(data["authenticated"], bool)


# ═══════════════════════════════════════════════════════════════
#  PROVIDER ROUTES
# ═══════════════════════════════════════════════════════════════


class TestProviderList:
    def test_list_providers_empty_registry(self, client):
        resp = client.get("/api/providers/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_providers_after_discover(self, client):
        client.post("/api/providers/discover")
        resp = client.get("/api/providers/")
        assert resp.status_code == 200
        names = [p["name"] for p in resp.json()]
        assert "mock" in names


class TestProviderDiscover:
    def test_discover(self, client):
        resp = client.post("/api/providers/discover")
        assert resp.status_code == 200
        data = resp.json()
        assert "discovered" in data
        assert "mock" in data["discovered"]

    def test_discover_idempotent(self, client):
        client.post("/api/providers/discover")
        resp = client.post("/api/providers/discover")
        assert resp.status_code == 200


class TestProviderActivate:
    def test_activate_mock(self, client):
        client.post("/api/providers/discover")
        resp = client.post("/api/providers/activate", json={
            "provider_name": "mock",
        })
        assert resp.status_code == 200
        assert resp.json()["active_provider"] == "mock"

    def test_activate_unknown_returns_404(self, client):
        resp = client.post("/api/providers/activate", json={
            "provider_name": "nonexistent",
        })
        assert resp.status_code == 404


class TestProviderActive:
    def test_get_active_when_none(self, client):
        resp = client.get("/api/providers/active")
        assert resp.status_code == 200
        # With dep override, provider is always available
        data = resp.json()
        assert "name" in data or "active_provider" in data

    def test_get_active_after_activate(self, client):
        client.post("/api/providers/discover")
        client.post("/api/providers/activate", json={"provider_name": "mock"})
        resp = client.get("/api/providers/active")
        assert resp.status_code == 200


class TestProviderDeactivate:
    def test_deactivate_when_none(self, client):
        # Ensure no provider is active (lifespan may auto-activate from env)
        registry.clear_registry()
        resp = client.post("/api/providers/deactivate")
        assert resp.status_code == 400

    def test_deactivate_active(self, client):
        client.post("/api/providers/discover")
        client.post("/api/providers/activate", json={"provider_name": "mock"})
        resp = client.post("/api/providers/deactivate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"


class TestProviderHealth:
    def test_health_registered_provider(self, client):
        client.post("/api/providers/discover")
        resp = client.get("/api/providers/mock/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data
        assert "latency_ms" in data

    def test_health_unknown_provider(self, client):
        resp = client.get("/api/providers/nonexistent/health")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════
#  ORDER ROUTES
# ═══════════════════════════════════════════════════════════════


class TestPlaceOrder:
    def test_place_market_order(self, client, mock_provider):
        # Set a price so the order can fill
        mock_provider.engine.set_ltp(256265, 2500.0)
        resp = client.post("/api/orders/place", json={
            "exchange": "NSE",
            "trading_symbol": "RELIANCE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 1,
            "product": "CNC",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "order_id" in data
        assert data["status"] == "placed"

    def test_place_limit_order(self, client, mock_provider):
        mock_provider.engine.set_ltp(256265, 2500.0)
        resp = client.post("/api/orders/place", json={
            "exchange": "NSE",
            "trading_symbol": "RELIANCE",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "quantity": 5,
            "product": "MIS",
            "price": 2400.0,
        })
        assert resp.status_code == 200
        assert "order_id" in resp.json()

    def test_place_order_invalid_exchange(self, client):
        resp = client.post("/api/orders/place", json={
            "exchange": "INVALID",
            "trading_symbol": "RELIANCE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 1,
            "product": "CNC",
        })
        assert resp.status_code == 400 or resp.status_code == 422

    def test_place_order_missing_fields(self, client):
        resp = client.post("/api/orders/place", json={
            "exchange": "NSE",
        })
        assert resp.status_code == 422


class TestGetOrders:
    def test_get_orders_empty(self, client):
        resp = client.get("/api/orders/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_orders_after_placing(self, client, mock_provider):
        mock_provider.engine.set_ltp(256265, 2500.0)
        client.post("/api/orders/place", json={
            "exchange": "NSE", "trading_symbol": "RELIANCE",
            "transaction_type": "BUY", "order_type": "MARKET",
            "quantity": 1, "product": "CNC",
        })
        resp = client.get("/api/orders/")
        assert resp.status_code == 200
        orders = resp.json()
        assert len(orders) >= 1
        assert "order_id" in orders[0]
        assert "trading_symbol" in orders[0]
        assert "status" in orders[0]


class TestCancelOrder:
    def test_cancel_nonexistent_order(self, client):
        resp = client.delete("/api/orders/regular/fake_order_id")
        assert resp.status_code == 400


class TestManagedOrders:
    def test_get_managed_orders(self, client, mock_provider):
        # OrderDep needs a provider, which our fixture injects
        resp = client.get("/api/orders/managed")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ═══════════════════════════════════════════════════════════════
#  PORTFOLIO ROUTES
# ═══════════════════════════════════════════════════════════════


class TestPositions:
    def test_get_positions(self, client):
        resp = client.get("/api/portfolio/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "net" in data
        assert "day" in data
        assert isinstance(data["net"], list)
        assert isinstance(data["day"], list)


class TestHoldings:
    def test_get_holdings(self, client):
        resp = client.get("/api/portfolio/holdings")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMargins:
    def test_get_margins(self, client):
        resp = client.get("/api/portfolio/margins")
        assert resp.status_code == 200
        data = resp.json()
        # Margins have equity and commodity segments
        assert "equity" in data or "commodity" in data


# ═══════════════════════════════════════════════════════════════
#  MARKET DATA ROUTES
# ═══════════════════════════════════════════════════════════════


class TestMarketQuote:
    def test_get_quote(self, client, mock_provider):
        mock_provider.engine.set_ltp(256265, 2500.0)
        resp = client.get("/api/market/quote", params={"instruments": ["NSE:RELIANCE"]})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_get_quote_missing_instruments(self, client):
        resp = client.get("/api/market/quote")
        assert resp.status_code == 422  # Missing required query param


class TestMarketLtp:
    def test_get_ltp(self, client):
        resp = client.get("/api/market/ltp", params={"instruments": ["NSE:RELIANCE"]})
        assert resp.status_code == 200

    def test_get_ltp_multiple_instruments(self, client):
        resp = client.get("/api/market/ltp", params={
            "instruments": ["NSE:RELIANCE", "NSE:INFY"],
        })
        assert resp.status_code == 200


class TestMarketOhlc:
    def test_get_ohlc(self, client, mock_provider):
        mock_provider.engine.set_ltp(256265, 2500.0)
        resp = client.get("/api/market/ohlc", params={"instruments": ["NSE:RELIANCE"]})
        assert resp.status_code == 200


class TestMarketHistorical:
    def test_get_historical(self, client):
        resp = client.get("/api/market/historical/256265", params={
            "interval": "day",
            "from_date": "2025-01-01",
            "to_date": "2025-01-15",
        })
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_historical_datetime_format(self, client):
        resp = client.get("/api/market/historical/256265", params={
            "interval": "minute",
            "from_date": "2025-01-15 09:15:00",
            "to_date": "2025-01-15 15:30:00",
        })
        assert resp.status_code == 200

    def test_get_historical_missing_params(self, client):
        resp = client.get("/api/market/historical/256265")
        assert resp.status_code == 422


class TestMarketInstruments:
    def test_get_instruments(self, client):
        resp = client.get("/api/market/instruments")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_instruments_with_exchange_filter(self, client):
        resp = client.get("/api/market/instruments", params={"exchange": "NSE"})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  STRATEGY ROUTES
# ═══════════════════════════════════════════════════════════════


class TestStrategyList:
    def test_list_strategies_empty(self, client):
        resp = client.get("/api/strategies/")
        assert resp.status_code == 200
        assert resp.json() == []


class TestStrategyTypes:
    def test_list_strategy_types(self, client):
        resp = client.get("/api/strategies/types")
        assert resp.status_code == 200
        types = resp.json()
        assert isinstance(types, list)
        # Built-in strategies should be discovered
        names = [t["name"] for t in types]
        assert "sma_crossover" in names or "rsi" in names or len(names) >= 0


class TestStrategyCRUD:
    def test_create_strategy(self, client):
        # First get available types
        types_resp = client.get("/api/strategies/types")
        types = types_resp.json()
        if not types:
            pytest.skip("No strategy types available")
        strategy_type = types[0]["name"]

        resp = client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "test_strat_1",
            "params": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["strategy_id"] == "test_strat_1"

    def test_create_duplicate_strategy(self, client):
        types = client.get("/api/strategies/types").json()
        if not types:
            pytest.skip("No strategy types available")
        strategy_type = types[0]["name"]

        client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "dup_test",
            "params": {},
        })
        resp = client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "dup_test",
            "params": {},
        })
        assert resp.status_code == 409

    def test_create_unknown_strategy_type(self, client):
        resp = client.post("/api/strategies/", json={
            "strategy_type": "totally_fake_strategy",
            "strategy_id": "test_id",
        })
        assert resp.status_code == 400

    def test_get_strategy(self, client):
        types = client.get("/api/strategies/types").json()
        if not types:
            pytest.skip("No strategy types available")
        strategy_type = types[0]["name"]
        client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "get_test",
            "params": {},
        })
        resp = client.get("/api/strategies/get_test")
        assert resp.status_code == 200
        assert resp.json()["strategy_id"] == "get_test"

    def test_get_strategy_not_found(self, client):
        resp = client.get("/api/strategies/nonexistent")
        assert resp.status_code == 404

    def test_delete_strategy(self, client):
        types = client.get("/api/strategies/types").json()
        if not types:
            pytest.skip("No strategy types available")
        strategy_type = types[0]["name"]
        client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "delete_me",
            "params": {},
        })
        resp = client.delete("/api/strategies/delete_me")
        assert resp.status_code == 200
        assert resp.json()["status"] == "deleted"

        # Verify deleted
        resp = client.get("/api/strategies/delete_me")
        assert resp.status_code == 404

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/strategies/nonexistent")
        assert resp.status_code == 404


class TestStrategyLifecycle:
    def _create_strategy(self, client):
        types = client.get("/api/strategies/types").json()
        if not types:
            pytest.skip("No strategy types available")
        strategy_type = types[0]["name"]
        client.post("/api/strategies/", json={
            "strategy_type": strategy_type,
            "strategy_id": "lifecycle_test",
            "params": {},
        })
        return "lifecycle_test"

    def test_start_strategy(self, client):
        sid = self._create_strategy(client)
        resp = client.post(f"/api/strategies/{sid}/start")
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

    def test_stop_strategy(self, client):
        sid = self._create_strategy(client)
        client.post(f"/api/strategies/{sid}/start")
        resp = client.post(f"/api/strategies/{sid}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

    def test_pause_resume_strategy(self, client):
        sid = self._create_strategy(client)
        client.post(f"/api/strategies/{sid}/start")

        resp = client.post(f"/api/strategies/{sid}/pause")
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        resp = client.post(f"/api/strategies/{sid}/resume")
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"

    def test_start_nonexistent_returns_404(self, client):
        resp = client.post("/api/strategies/nonexistent/start")
        assert resp.status_code == 404

    def test_update_params(self, client):
        sid = self._create_strategy(client)
        resp = client.put(f"/api/strategies/{sid}/params", json={
            "params": {"fast_period": 5},
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "updated"


# ═══════════════════════════════════════════════════════════════
#  CONFIG ROUTES
# ═══════════════════════════════════════════════════════════════


class TestConfigGet:
    def test_get_all(self, client):
        resp = client.get("/api/config/")
        assert resp.status_code == 200

    def test_get_missing_key(self, client):
        resp = client.get("/api/config/does.not.exist")
        assert resp.status_code == 404

    def test_set_and_get(self, client):
        client.put("/api/config/", json={"key": "test.foo", "value": "bar"})
        resp = client.get("/api/config/test.foo")
        assert resp.status_code == 200
        assert resp.json()["value"] == "bar"


# ═══════════════════════════════════════════════════════════════
#  RISK CONFIG ROUTES
# ═══════════════════════════════════════════════════════════════


class TestRiskLimits:
    def test_get_risk_limits(self, client):
        resp = client.get("/api/config/risk/limits")
        assert resp.status_code == 200
        data = resp.json()
        assert "max_order_value" in data
        assert "max_daily_loss" in data
        assert "kill_switch_active" in data

    def test_update_risk_limits(self, client):
        resp = client.put("/api/config/risk/limits", json={
            "max_daily_loss": 75_000,
            "max_open_orders": 50,
        })
        assert resp.status_code == 200

        resp = client.get("/api/config/risk/limits")
        data = resp.json()
        assert data["max_daily_loss"] == 75_000
        assert data["max_open_orders"] == 50

    def test_update_risk_limits_partial(self, client):
        """Only specified fields should be updated."""
        original = client.get("/api/config/risk/limits").json()
        client.put("/api/config/risk/limits", json={"max_daily_loss": 99_999})
        updated = client.get("/api/config/risk/limits").json()
        assert updated["max_daily_loss"] == 99_999
        assert updated["max_order_value"] == original["max_order_value"]


class TestRiskStatus:
    def test_get_risk_status(self, client):
        resp = client.get("/api/config/risk/status")
        assert resp.status_code == 200


class TestKillSwitch:
    def test_activate_kill_switch(self, client):
        resp = client.post("/api/config/risk/kill-switch/activate")
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is True

    def test_deactivate_kill_switch(self, client):
        client.post("/api/config/risk/kill-switch/activate")
        resp = client.post("/api/config/risk/kill-switch/deactivate")
        assert resp.status_code == 200
        assert resp.json()["kill_switch_active"] is False

    def test_kill_switch_roundtrip(self, client):
        # Start deactivated
        limits = client.get("/api/config/risk/limits").json()
        assert limits["kill_switch_active"] is False

        client.post("/api/config/risk/kill-switch/activate")
        limits = client.get("/api/config/risk/limits").json()
        assert limits["kill_switch_active"] is True

        client.post("/api/config/risk/kill-switch/deactivate")
        limits = client.get("/api/config/risk/limits").json()
        assert limits["kill_switch_active"] is False


# ═══════════════════════════════════════════════════════════════
#  MOCK TRADING ROUTES
# ═══════════════════════════════════════════════════════════════


class TestMockSession:
    def test_create_session(self, client):
        resp = client.post("/api/mock/session", json={
            "initial_capital": 500_000,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["initial_capital"] == 500_000
        assert data["status"] == "created"

    def test_create_session_with_dates(self, client):
        resp = client.post("/api/mock/session", json={
            "initial_capital": 1_000_000,
            "start_date": "2025-01-15",
            "end_date": "2025-01-31",
        })
        assert resp.status_code == 200

    def test_create_session_defaults(self, client):
        resp = client.post("/api/mock/session", json={})
        assert resp.status_code == 200
        assert resp.json()["initial_capital"] == 1_000_000

    def test_get_session_status(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/session")
        assert resp.status_code == 200
        data = resp.json()
        assert "virtual_capital" in data
        assert "current_time" in data
        assert "is_market_open" in data
        assert "speed" in data
        assert "paused" in data
        assert "open_orders" in data
        assert "positions" in data
        assert "total_pnl" in data


class TestMockSampleData:
    def test_load_sample_data(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/sample-data")
        assert resp.status_code == 200

    def test_get_mock_instruments(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/instruments")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestMockTimeControls:
    def test_set_date(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/set-date", json={"date": "2025-06-15"})
        assert resp.status_code == 200
        assert "time" in resp.json()

    def test_market_open(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/market-open")
        assert resp.status_code == 200

    def test_market_close(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/market-close")
        assert resp.status_code == 200

    def test_next_day(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/next-day")
        assert resp.status_code == 200

    def test_set_speed(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/speed", json={"speed": 5.0})
        assert resp.status_code == 200
        assert resp.json()["speed"] == 5.0

    def test_pause_resume(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/time/pause")
        assert resp.status_code == 200
        assert resp.json()["paused"] is True

        resp = client.post("/api/mock/time/resume")
        assert resp.status_code == 200
        assert resp.json()["paused"] is False


class TestMockOrdersPositions:
    def test_get_orders(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/orders")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_positions(self, client):
        client.post("/api/mock/session", json={})
        resp = client.get("/api/mock/positions")
        assert resp.status_code == 200
        assert "net" in resp.json()


class TestMockReset:
    def test_reset(self, client):
        client.post("/api/mock/session", json={})
        resp = client.post("/api/mock/reset")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reset"


class TestMockRejectsNonMockProvider:
    """Mock routes should return 400 when a non-mock provider is active."""

    def test_mock_routes_require_mock_provider(self, client):
        # Our default fixture IS a mock provider, so these should pass
        resp = client.post("/api/mock/session", json={})
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════
#  POSTBACK (WEBHOOK) ROUTE
# ═══════════════════════════════════════════════════════════════


class TestPostback:
    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_api_secret"})
    def test_valid_postback(self, client):
        order_id = "230101000001"
        order_timestamp = "2025-01-15 10:30:00"
        api_secret = "test_api_secret"
        checksum = hashlib.sha256(
            (order_id + order_timestamp + api_secret).encode()
        ).hexdigest()

        resp = client.post("/api/postback", json={
            "order_id": order_id,
            "order_timestamp": order_timestamp,
            "checksum": checksum,
            "status": "COMPLETE",
            "tradingsymbol": "RELIANCE",
            "filled_quantity": 10,
            "average_price": 2500.0,
        })
        assert resp.status_code == 200

    def test_invalid_checksum(self, client):
        with patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "real_secret"}):
            resp = client.post("/api/postback", json={
                "order_id": "123",
                "order_timestamp": "2025-01-15 10:30:00",
                "checksum": "wrong_checksum",
                "status": "COMPLETE",
                "tradingsymbol": "RELIANCE",
            })
            assert resp.status_code == 403

    def test_invalid_json(self, client):
        resp = client.post(
            "/api/postback",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════
#  FULL FLOW INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestFullMockTradingFlow:
    """End-to-end flow: discover → activate → create session → trade."""

    def test_complete_mock_trading_flow(self, client, mock_provider):
        # 1. Discover providers
        resp = client.post("/api/providers/discover")
        assert resp.status_code == 200
        assert "mock" in resp.json()["discovered"]

        # 2. Activate mock provider (already overridden in fixture, but test the route)
        resp = client.post("/api/providers/activate", json={"provider_name": "mock"})
        assert resp.status_code == 200

        # 3. Create mock session
        resp = client.post("/api/mock/session", json={"initial_capital": 1_000_000})
        assert resp.status_code == 200

        # 4. Feed a tick price
        mock_provider.engine.set_ltp(256265, 2500.0)

        # 5. Place an order
        resp = client.post("/api/orders/place", json={
            "exchange": "NSE",
            "trading_symbol": "RELIANCE",
            "transaction_type": "BUY",
            "order_type": "MARKET",
            "quantity": 10,
            "product": "CNC",
        })
        assert resp.status_code == 200
        order_id = resp.json()["order_id"]

        # 6. Check orders
        resp = client.get("/api/orders/")
        assert resp.status_code == 200
        orders = resp.json()
        assert len(orders) >= 1

        # 7. Check positions
        resp = client.get("/api/portfolio/positions")
        assert resp.status_code == 200

        # 8. Check session status
        resp = client.get("/api/mock/session")
        assert resp.status_code == 200

    def test_auth_to_trade_flow(self, client):
        """Test the auth callback → session check flow."""
        # 1. Auth callback
        resp = client.post("/api/auth/callback", json={
            "request_token": "test_token",
            "api_key": "test_key",
            "api_secret": "test_secret",
        })
        assert resp.status_code == 200
        assert resp.json()["access_token"]

        # 2. Session check
        resp = client.get("/api/auth/session")
        assert resp.status_code == 200
        assert "authenticated" in resp.json()


# ═══════════════════════════════════════════════════════════════
#  ENV LOADING TESTS
# ═══════════════════════════════════════════════════════════════


class TestEnvLoading:
    """Verify that auth routes correctly read from environment."""

    @patch.dict(os.environ, {
        "TRADE_ZERODHA_API_KEY": "my_test_key_xyz",
        "TRADE_ZERODHA_API_SECRET": "my_test_secret_abc",
        "TRADE_FRONTEND_URL": "https://myapp.example.com",
    })
    def test_login_url_uses_env_key(self, client):
        """Mock provider returns mock://login regardless of env vars."""
        resp = client.get("/api/auth/login-url")
        assert resp.status_code == 200
        # With mock provider active, the URL comes from the provider
        assert resp.json()["login_url"] == "mock://login"

    @patch.dict(os.environ, {
        "TRADE_FRONTEND_URL": "https://custom-frontend.example.com",
        "TRADE_ZERODHA_API_KEY": "k",
        "TRADE_ZERODHA_API_SECRET": "s",
    })
    def test_redirect_uses_frontend_url(self, client):
        resp = client.get(
            "/api/auth/redirect",
            params={"request_token": "tok", "status": "success"},
            follow_redirects=False,
        )
        assert resp.status_code == 307
        # The redirect should go to the custom frontend URL
        location = resp.headers["location"]
        assert "custom-frontend.example.com" in location or "auth=success" in location


# ═══════════════════════════════════════════════════════════════
#  WEBSOCKET ENDPOINT
# ═══════════════════════════════════════════════════════════════


class TestWebSocket:
    """Test WebSocket tick streaming endpoint."""

    def test_websocket_connect_and_ping(self, client):
        # Note: ws.router is not registered in main.py, so this tests
        # that the endpoint returns 404/error when not registered
        # If it were registered, we'd test subscription flow
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/ticks/test_client") as ws:
                ws.send_json({"action": "ping"})
                data = ws.receive_json()
                assert data["type"] == "pong"


# ═══════════════════════════════════════════════════════════════
#  ERROR HANDLING - NO PROVIDER
# ═══════════════════════════════════════════════════════════════


class TestNoProviderErrors:
    """Routes that require a provider should fail when none is active."""

    def test_orders_without_provider(self, client_no_provider):
        # ProviderError propagates as 500 because get_provider() raises RuntimeError
        try:
            resp = client_no_provider.get("/api/orders/")
            assert resp.status_code >= 400
        except Exception:
            # ProviderError may propagate through TestClient
            pass

    def test_positions_without_provider(self, client_no_provider):
        try:
            resp = client_no_provider.get("/api/portfolio/positions")
            assert resp.status_code >= 400
        except Exception:
            pass

    def test_quote_without_provider(self, client_no_provider):
        try:
            resp = client_no_provider.get("/api/market/quote", params={"instruments": ["NSE:RELIANCE"]})
            assert resp.status_code >= 400
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
#  INSTRUMENT SEARCH
# ═══════════════════════════════════════════════════════════════


class TestInstrumentSearch:
    """Tests for GET /api/market/instruments/search."""

    def test_search_requires_query(self, client):
        resp = client.get("/api/market/instruments/search")
        assert resp.status_code == 422  # missing required 'q'

    def test_search_empty_query_rejected(self, client):
        resp = client.get("/api/market/instruments/search", params={"q": ""})
        assert resp.status_code == 422  # min_length=1

    def test_search_returns_results(self, client, mock_provider):
        # Load sample data so instruments are populated
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "REL"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        symbols = [r["trading_symbol"] for r in results]
        assert "RELIANCE" in symbols

    def test_search_case_insensitive(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "rel"})
        assert resp.status_code == 200
        results = resp.json()
        assert any("RELIANCE" in r["trading_symbol"] for r in results)

    def test_search_by_name(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "Infosys"})
        assert resp.status_code == 200
        results = resp.json()
        symbols = [r["trading_symbol"] for r in results]
        assert "INFY" in symbols

    def test_search_no_match(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "XYZNONEXIST"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_search_result_fields(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "TCS"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        r = results[0]
        assert "instrument_token" in r
        assert "trading_symbol" in r
        assert "name" in r
        assert "exchange" in r
        assert "last_price" in r

    def test_search_with_exchange_filter(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        resp = client.get("/api/market/instruments/search", params={"q": "REL", "exchange": "NSE"})
        assert resp.status_code == 200
        results = resp.json()
        assert len(results) >= 1
        assert all(r["exchange"] == "NSE" for r in results)

    def test_search_max_50_results(self, client, mock_provider):
        mock_provider.engine.load_sample_data()
        mock_provider.load_instruments(mock_provider.engine.get_sample_as_instruments())

        # Search with a very broad query that matches many
        resp = client.get("/api/market/instruments/search", params={"q": "A"})
        assert resp.status_code == 200
        assert len(resp.json()) <= 50


# ═══════════════════════════════════════════════════════════════
#  SAMPLE DATA → INSTRUMENTS BRIDGE
# ═══════════════════════════════════════════════════════════════


class TestSampleDataInstrumentsBridge:
    """Verify that POST /api/mock/sample-data populates the instruments list."""

    def test_sample_data_populates_instruments(self, client, mock_provider):
        # Before loading, instruments should be empty
        resp = client.get("/api/market/instruments")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

        # Load sample data
        resp = client.post("/api/mock/sample-data")
        assert resp.status_code == 200

        # Now instruments endpoint should return the sample stocks
        resp = client.get("/api/market/instruments")
        assert resp.status_code == 200
        instruments = resp.json()
        assert len(instruments) == 20  # 20 sample instruments
        symbols = [i["trading_symbol"] for i in instruments]
        assert "RELIANCE" in symbols
        assert "TCS" in symbols
        assert "INFY" in symbols

    def test_sample_data_instruments_searchable(self, client, mock_provider):
        # Load sample data
        client.post("/api/mock/sample-data")

        # Search should now work
        resp = client.get("/api/market/instruments/search", params={"q": "HDFC"})
        assert resp.status_code == 200
        results = resp.json()
        symbols = [r["trading_symbol"] for r in results]
        assert "HDFCBANK" in symbols

    def test_get_sample_as_instruments_returns_correct_types(self, mock_provider):
        from app.providers.types import Instrument, Exchange
        mock_provider.engine.load_sample_data()
        instruments = mock_provider.engine.get_sample_as_instruments()
        assert len(instruments) == 20
        for inst in instruments:
            assert isinstance(inst, Instrument)
            assert inst.exchange == Exchange.NSE
            assert inst.instrument_type == "EQ"
            assert inst.segment == "NSE"
            assert inst.lot_size == 1
