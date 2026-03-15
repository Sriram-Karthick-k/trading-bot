"""
Configuration management routes.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ConfigDep, RiskDep

router = APIRouter(prefix="/config", tags=["config"])


class SetConfigRequest(BaseModel):
    key: str
    value: str
    scope: str = "global"


class SetRiskLimitsRequest(BaseModel):
    max_order_value: float | None = None
    max_position_value: float | None = None
    max_loss_per_trade: float | None = None
    max_daily_loss: float | None = None
    max_open_orders: int | None = None
    max_open_positions: int | None = None
    max_quantity_per_order: int | None = None
    max_orders_per_minute: int | None = None


# Keys whose values must never be exposed via the API
_SENSITIVE_PATTERNS = {"api_key", "api_secret", "secret", "password", "token", "credential"}


def _redact(key: str, value: object) -> object:
    """Replace sensitive config values with a redacted marker."""
    lower = key.lower()
    if any(pat in lower for pat in _SENSITIVE_PATTERNS):
        return "********"
    return value


@router.get("/")
async def get_all_config(config: ConfigDep):
    """Get all configuration values (secrets are redacted)."""
    raw = config.get_all()
    return {k: _redact(k, v) for k, v in raw.items()}


@router.get("/{key}")
async def get_config(key: str, config: ConfigDep):
    try:
        value = config.get(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return {"key": key, "value": value}


@router.put("/")
async def set_config(body: SetConfigRequest, config: ConfigDep):
    config.set_db_override(body.key, body.value)
    return {"key": body.key, "value": body.value, "scope": body.scope}


@router.get("/risk/limits")
async def get_risk_limits(risk: RiskDep):
    limits = risk.limits
    return {
        "max_order_value": limits.max_order_value,
        "max_position_value": limits.max_position_value,
        "max_loss_per_trade": limits.max_loss_per_trade,
        "max_daily_loss": limits.max_daily_loss,
        "max_open_orders": limits.max_open_orders,
        "max_open_positions": limits.max_open_positions,
        "max_quantity_per_order": limits.max_quantity_per_order,
        "max_orders_per_minute": limits.max_orders_per_minute,
        "kill_switch_active": limits.kill_switch_active,
    }


@router.put("/risk/limits")
async def update_risk_limits(body: SetRiskLimitsRequest, risk: RiskDep):
    limits = risk.limits
    if body.max_order_value is not None:
        limits.max_order_value = body.max_order_value
    if body.max_position_value is not None:
        limits.max_position_value = body.max_position_value
    if body.max_loss_per_trade is not None:
        limits.max_loss_per_trade = body.max_loss_per_trade
    if body.max_daily_loss is not None:
        limits.max_daily_loss = body.max_daily_loss
    if body.max_open_orders is not None:
        limits.max_open_orders = body.max_open_orders
    if body.max_open_positions is not None:
        limits.max_open_positions = body.max_open_positions
    if body.max_quantity_per_order is not None:
        limits.max_quantity_per_order = body.max_quantity_per_order
    if body.max_orders_per_minute is not None:
        limits.max_orders_per_minute = body.max_orders_per_minute
    risk.update_limits(limits)
    return {"status": "updated"}


@router.get("/risk/status")
async def get_risk_status(risk: RiskDep):
    return risk.get_status()


@router.post("/risk/kill-switch/activate")
async def activate_kill_switch(risk: RiskDep):
    risk.activate_kill_switch()
    return {"kill_switch_active": True}


@router.post("/risk/kill-switch/deactivate")
async def deactivate_kill_switch(risk: RiskDep):
    risk.deactivate_kill_switch()
    return {"kill_switch_active": False}
