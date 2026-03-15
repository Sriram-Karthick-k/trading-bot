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

router = APIRouter(prefix="/postback", tags=["postback"])

logger = logging.getLogger(__name__)


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

    The JSON payload is posted as a raw HTTP body.
    Validates the checksum to ensure the request is from Kite Connect.
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

    # TODO: Forward the order update to OrderManager / Strategy engine
    # For now, just acknowledge receipt.

    return {"status": "ok", "order_id": order_id}
