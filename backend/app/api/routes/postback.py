"""
Postback (webhook) route — receives order status updates from Zerodha.

Zerodha POSTs a JSON payload to the registered postback_url whenever
an order's status changes (COMPLETE, REJECTED, CANCELLED, UPDATE).

Configure this URL in Kite Connect Developer Console:
  Postback URL = https://localhost:8000/api/postback

Docs: https://kite.trade/docs/connect/v3/postbacks/
"""

from __future__ import annotations

import hashlib
import logging
import os

from fastapi import APIRouter, Request, HTTPException

from app.api.deps import get_order_manager, get_trading_engine
from app.api.routes.ws import manager as ws_manager
from app.providers.zerodha.mapper import ZerodhaMapper

router = APIRouter(prefix="/postback", tags=["postback"])

logger = logging.getLogger(__name__)

_mapper = ZerodhaMapper()


def _verify_checksum(order_id: str, order_timestamp: str, checksum: str) -> bool:
    """
    Verify the Zerodha postback checksum.

    Checksum = SHA-256(order_id + order_timestamp + api_secret)
    """
    api_secret = os.environ.get("TRADE_ZERODHA_API_SECRET", "")
    if not api_secret:
        logger.warning("Cannot verify postback checksum: TRADE_ZERODHA_API_SECRET not set")
        return False
    expected = hashlib.sha256(
        (order_id + order_timestamp + api_secret).encode()
    ).hexdigest()
    return expected == checksum


@router.post("/")
async def handle_postback(request: Request):
    """
    Receive order update webhooks from Zerodha.

    Flow:
      1. Parse & validate checksum
      2. Convert payload to Order via ZerodhaMapper
      3. Forward to OrderManager.on_order_update() (updates ManagedOrder state)
      4. Forward to TradingEngine._on_order_update() (engine event logging)
      5. Broadcast to frontend via WebSocket
      6. Return 200 OK
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    order_id = payload.get("order_id", "")
    order_timestamp = payload.get("order_timestamp", "")
    checksum = payload.get("checksum", "")
    status = payload.get("status", "")
    tradingsymbol = payload.get("tradingsymbol", "")

    # Verify checksum
    if not _verify_checksum(order_id, order_timestamp, checksum):
        logger.warning(
            "Postback checksum mismatch for order %s — possible spoofed request",
            order_id,
        )
        raise HTTPException(status_code=403, detail="Invalid checksum")

    logger.info(
        "Postback received: order=%s symbol=%s status=%s filled=%s avg_price=%s",
        order_id,
        tradingsymbol,
        status,
        payload.get("filled_quantity"),
        payload.get("average_price"),
    )

    # Convert to typed Order and forward to subsystems
    try:
        order = _mapper.to_order(payload)

        # 1. Update OrderManager's tracked order state
        try:
            order_mgr = get_order_manager()
            await order_mgr.on_order_update(order)
        except RuntimeError:
            # No active provider yet — OrderManager not initialized
            logger.debug("OrderManager not available, skipping order update")

        # 2. Forward to TradingEngine for event logging
        try:
            engine = get_trading_engine()
            engine._on_order_update(payload)
        except RuntimeError:
            # Engine not initialized
            logger.debug("TradingEngine not available, skipping engine event")

        # 3. Broadcast order update to connected frontend clients via WebSocket
        await ws_manager.broadcast_data("orders_update", {
            "source": "postback",
            "order_id": order_id,
            "status": status,
            "tradingsymbol": tradingsymbol,
            "filled_quantity": payload.get("filled_quantity", 0),
            "average_price": payload.get("average_price", 0),
        })

    except Exception as e:
        # Log but don't fail the postback — Zerodha expects 200 OK
        logger.error("Error processing postback for order %s: %s", order_id, e)

    return {"status": "ok", "order_id": order_id}
