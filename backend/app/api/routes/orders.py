"""
Order management routes.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ProviderDep, OrderDep
from app.providers.types import (
    Exchange,
    OrderType,
    ProductType,
    TransactionType,
    Variety,
    Validity,
    OrderRequest,
)

router = APIRouter(prefix="/orders", tags=["orders"])


class PlaceOrderRequest(BaseModel):
    exchange: str
    trading_symbol: str
    transaction_type: str
    order_type: str
    quantity: int
    product: str
    price: float | None = None
    trigger_price: float | None = None
    variety: str = "regular"
    validity: str = "DAY"
    disclosed_quantity: int | None = None
    tag: str | None = None


class ModifyOrderRequest(BaseModel):
    order_type: str | None = None
    quantity: int | None = None
    price: float | None = None
    trigger_price: float | None = None
    validity: str | None = None
    disclosed_quantity: int | None = None


@router.post("/place")
async def place_order(body: PlaceOrderRequest, provider: ProviderDep):
    try:
        request = OrderRequest(
            exchange=Exchange(body.exchange),
            tradingsymbol=body.trading_symbol,
            transaction_type=TransactionType(body.transaction_type),
            order_type=OrderType(body.order_type),
            quantity=body.quantity,
            product=ProductType(body.product),
            price=body.price,
            trigger_price=body.trigger_price,
            variety=Variety(body.variety),
            validity=Validity(body.validity),
            disclosed_quantity=body.disclosed_quantity,
            tag=body.tag,
        )
        order_id = await provider.place_order(request)
        return {"order_id": order_id, "status": "placed"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{variety}/{order_id}")
async def modify_order(
    variety: str, order_id: str, body: ModifyOrderRequest, provider: ProviderDep
):
    try:
        params = {}
        if body.order_type:
            params["order_type"] = body.order_type
        if body.quantity:
            params["quantity"] = body.quantity
        if body.price is not None:
            params["price"] = body.price
        if body.trigger_price is not None:
            params["trigger_price"] = body.trigger_price
        if body.validity:
            params["validity"] = body.validity
        if body.disclosed_quantity is not None:
            params["disclosed_quantity"] = body.disclosed_quantity

        new_id = await provider.modify_order(
            variety=Variety(variety),
            order_id=order_id,
            params=params,
        )
        return {"order_id": new_id, "status": "modified"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{variety}/{order_id}")
async def cancel_order(variety: str, order_id: str, provider: ProviderDep):
    try:
        result = await provider.cancel_order(variety=Variety(variety), order_id=order_id)
        return {"order_id": result, "status": "cancelled"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
async def get_orders(provider: ProviderDep):
    orders = await provider.get_orders()
    return [
        {
            "order_id": o.order_id,
            "exchange_order_id": o.exchange_order_id,
            "exchange": o.exchange.value,
            "trading_symbol": o.tradingsymbol,
            "transaction_type": o.transaction_type.value,
            "order_type": o.order_type.value,
            "product": o.product.value,
            "quantity": o.quantity,
            "filled_quantity": o.filled_quantity,
            "pending_quantity": o.pending_quantity,
            "price": o.price,
            "trigger_price": o.trigger_price,
            "average_price": o.average_price,
            "status": o.status.value,
            "status_message": o.status_message,
            "placed_at": o.order_timestamp.isoformat() if o.order_timestamp else None,
        }
        for o in orders
    ]


@router.get("/managed")
async def get_managed_orders(order_mgr: OrderDep):
    orders = order_mgr.get_all_orders()
    return [
        {
            "order_id": o.order_id,
            "strategy_id": o.strategy_id,
            "status": o.status.value,
            "filled_price": o.filled_price,
            "error_message": o.error_message,
            "placed_at": o.placed_at.isoformat(),
        }
        for o in orders
    ]
