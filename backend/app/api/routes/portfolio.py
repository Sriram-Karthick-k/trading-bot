"""
Portfolio routes – positions, holdings, margins.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ProviderDep

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/positions")
async def get_positions(provider: ProviderDep):
    data = await provider.get_positions()
    result = {"net": [], "day": []}
    for p in data.net:
        result["net"].append({
            "trading_symbol": p.tradingsymbol,
            "exchange": p.exchange.value,
            "product": p.product.value,
            "quantity": p.quantity,
            "average_price": p.average_price,
            "last_price": p.last_price,
            "pnl": p.pnl,
            "buy_quantity": p.buy_quantity,
            "sell_quantity": p.sell_quantity,
            "buy_price": p.buy_price,
            "sell_price": p.sell_price,
            "multiplier": p.multiplier,
        })
    for p in data.day:
        result["day"].append({
            "trading_symbol": p.tradingsymbol,
            "exchange": p.exchange.value,
            "product": p.product.value,
            "quantity": p.quantity,
            "average_price": p.average_price,
            "last_price": p.last_price,
            "pnl": p.pnl,
        })
    return result


@router.get("/holdings")
async def get_holdings(provider: ProviderDep):
    holdings = await provider.get_holdings()
    return [
        {
            "trading_symbol": h.tradingsymbol,
            "exchange": h.exchange.value,
            "isin": h.isin,
            "quantity": h.quantity,
            "t1_quantity": h.t1_quantity,
            "average_price": h.average_price,
            "last_price": h.last_price,
            "pnl": h.pnl,
            "day_change": h.day_change,
            "day_change_percentage": h.day_change_percentage,
        }
        for h in holdings
    ]


@router.get("/margins")
async def get_margins(provider: ProviderDep):
    margins = await provider.get_margins()
    return {
        "equity": {
            "available_cash": margins.equity.available_cash,
            "net": margins.equity.net,
            "opening_balance": margins.equity.opening_balance,
        } if margins.equity else None,
        "commodity": {
            "available_cash": margins.commodity.available_cash,
            "net": margins.commodity.net,
            "opening_balance": margins.commodity.opening_balance,
        } if margins.commodity else None,
    }
