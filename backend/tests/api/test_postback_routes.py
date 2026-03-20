"""
Tests for the Postback (webhook) route.

Covers:
  - POST /postback/          — receive Zerodha order status webhook
  - Checksum verification
  - Order forwarding to OrderManager
  - Engine event logging
  - WebSocket broadcasting
  - Error handling (invalid JSON, bad checksum, subsystem failures)
"""

from __future__ import annotations

import hashlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import deps
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
def client():
    return TestClient(app)


def _make_postback_payload(
    order_id: str = "250320000001234",
    tradingsymbol: str = "RELIANCE",
    status: str = "COMPLETE",
    api_secret: str = "test_secret",
    **overrides,
) -> dict:
    """Create a valid Zerodha postback payload with correct checksum."""
    order_timestamp = overrides.pop("order_timestamp", "2026-03-20 10:15:00")
    checksum = hashlib.sha256(
        (order_id + order_timestamp + api_secret).encode()
    ).hexdigest()

    payload = {
        "order_id": order_id,
        "tradingsymbol": tradingsymbol,
        "exchange": "NSE",
        "transaction_type": "BUY",
        "order_type": "MARKET",
        "product": "MIS",
        "variety": "regular",
        "status": status,
        "quantity": 10,
        "price": 0.0,
        "trigger_price": 0.0,
        "average_price": 2500.0,
        "filled_quantity": 10,
        "pending_quantity": 0,
        "cancelled_quantity": 0,
        "disclosed_quantity": 0,
        "validity": "DAY",
        "order_timestamp": order_timestamp,
        "exchange_timestamp": "2026-03-20 10:15:01",
        "checksum": checksum,
        **overrides,
    }
    return payload


# ═══════════════════════════════════════════════════════════════
#  Checksum Verification
# ═══════════════════════════════════════════════════════════════


class TestPostbackChecksum:
    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    def test_valid_checksum_accepted(self, client):
        """Request with correct checksum should be accepted."""
        payload = _make_postback_payload(api_secret="test_secret")
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    def test_invalid_checksum_rejected(self, client):
        """Request with wrong checksum should get 403."""
        payload = _make_postback_payload(api_secret="test_secret")
        payload["checksum"] = "deadbeef" * 8  # wrong checksum
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 403
        assert "Invalid checksum" in resp.json()["detail"]

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": ""})
    def test_missing_api_secret_rejects(self, client):
        """Without API secret set, checksum can't be verified → 403."""
        payload = _make_postback_payload(api_secret="anything")
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 403

    def test_invalid_json_returns_400(self, client):
        """Non-JSON body should get 400."""
        resp = client.post(
            "/api/postback/",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════
#  Order Forwarding
# ═══════════════════════════════════════════════════════════════


class TestPostbackForwarding:
    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine")
    @patch("app.api.routes.postback.get_order_manager")
    def test_forwards_to_order_manager(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """Postback should call OrderManager.on_order_update()."""
        mock_om = MagicMock()
        mock_om.on_order_update = AsyncMock()
        mock_get_om.return_value = mock_om

        mock_eng = MagicMock()
        mock_get_engine.return_value = mock_eng

        mock_ws.broadcast_data = AsyncMock()

        payload = _make_postback_payload(api_secret="test_secret")
        resp = client.post("/api/postback/", json=payload)

        assert resp.status_code == 200
        mock_om.on_order_update.assert_called_once()
        # Verify the Order object passed has the right order_id
        order_arg = mock_om.on_order_update.call_args[0][0]
        assert order_arg.order_id == "250320000001234"

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine")
    @patch("app.api.routes.postback.get_order_manager")
    def test_forwards_to_trading_engine(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """Postback should call TradingEngine._on_order_update()."""
        mock_om = MagicMock()
        mock_om.on_order_update = AsyncMock()
        mock_get_om.return_value = mock_om

        mock_eng = MagicMock()
        mock_get_engine.return_value = mock_eng

        mock_ws.broadcast_data = AsyncMock()

        payload = _make_postback_payload(api_secret="test_secret")
        resp = client.post("/api/postback/", json=payload)

        assert resp.status_code == 200
        mock_eng._on_order_update.assert_called_once_with(payload)

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine")
    @patch("app.api.routes.postback.get_order_manager")
    def test_broadcasts_via_websocket(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """Postback should broadcast order update via WebSocket."""
        mock_om = MagicMock()
        mock_om.on_order_update = AsyncMock()
        mock_get_om.return_value = mock_om

        mock_eng = MagicMock()
        mock_get_engine.return_value = mock_eng

        mock_ws.broadcast_data = AsyncMock()

        payload = _make_postback_payload(
            api_secret="test_secret",
            status="REJECTED",
            filled_quantity=0,
        )
        resp = client.post("/api/postback/", json=payload)

        assert resp.status_code == 200
        mock_ws.broadcast_data.assert_called_once()
        call_args = mock_ws.broadcast_data.call_args
        assert call_args[0][0] == "orders_update"
        assert call_args[0][1]["source"] == "postback"
        assert call_args[0][1]["status"] == "REJECTED"

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine", side_effect=RuntimeError)
    @patch("app.api.routes.postback.get_order_manager", side_effect=RuntimeError)
    def test_graceful_when_subsystems_unavailable(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """Postback should still return 200 even if engine/OM not initialized."""
        mock_ws.broadcast_data = AsyncMock()
        payload = _make_postback_payload(api_secret="test_secret")
        resp = client.post("/api/postback/", json=payload)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ═══════════════════════════════════════════════════════════════
#  Response Shape
# ═══════════════════════════════════════════════════════════════


class TestPostbackResponse:
    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    def test_returns_order_id(self, client):
        """Response should echo back the order_id."""
        payload = _make_postback_payload(
            order_id="999888777",
            api_secret="test_secret",
        )
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 200
        assert resp.json()["order_id"] == "999888777"

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine")
    @patch("app.api.routes.postback.get_order_manager")
    def test_complete_order_status(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """COMPLETE status should forward correctly."""
        mock_om = MagicMock()
        mock_om.on_order_update = AsyncMock()
        mock_get_om.return_value = mock_om

        mock_eng = MagicMock()
        mock_get_engine.return_value = mock_eng

        mock_ws.broadcast_data = AsyncMock()

        payload = _make_postback_payload(
            api_secret="test_secret",
            status="COMPLETE",
            filled_quantity=10,
            average_price=2500.0,
        )
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 200

        order_arg = mock_om.on_order_update.call_args[0][0]
        assert order_arg.status.value == "COMPLETE"
        assert order_arg.filled_quantity == 10
        assert order_arg.average_price == 2500.0

    @patch.dict(os.environ, {"TRADE_ZERODHA_API_SECRET": "test_secret"})
    @patch("app.api.routes.postback.ws_manager")
    @patch("app.api.routes.postback.get_trading_engine")
    @patch("app.api.routes.postback.get_order_manager")
    def test_rejected_order_status(
        self, mock_get_om, mock_get_engine, mock_ws, client,
    ):
        """REJECTED status should forward correctly."""
        mock_om = MagicMock()
        mock_om.on_order_update = AsyncMock()
        mock_get_om.return_value = mock_om

        mock_eng = MagicMock()
        mock_get_engine.return_value = mock_eng

        mock_ws.broadcast_data = AsyncMock()

        payload = _make_postback_payload(
            api_secret="test_secret",
            status="REJECTED",
            filled_quantity=0,
            average_price=0.0,
            status_message="Insufficient funds",
        )
        resp = client.post("/api/postback/", json=payload)
        assert resp.status_code == 200

        order_arg = mock_om.on_order_update.call_args[0][0]
        assert order_arg.status.value == "REJECTED"
        assert order_arg.status_message == "Insufficient funds"
