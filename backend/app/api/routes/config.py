"""
Configuration management routes.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ConfigDep, RiskDep, get_trading_mode, set_trading_mode

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


class SetTradingModeRequest(BaseModel):
    mode: str  # "live" or "paper"


# Keys whose values must never be exposed via the API
_SENSITIVE_PATTERNS = {"api_key", "api_secret", "secret", "password", "token", "credential"}


def _redact(key: str, value: object) -> object:
    """Replace sensitive config values with a redacted marker."""
    lower = key.lower()
    if any(pat in lower for pat in _SENSITIVE_PATTERNS):
        return "********"
    return value


# ── Trading Mode ─────────────────────────────────────────────
# IMPORTANT: These must be declared BEFORE the /{key} catch-all route,
# otherwise FastAPI matches "trading-mode" as a {key} path parameter.


@router.get("/trading-mode")
async def get_current_trading_mode():
    """Get the current trading mode (live or paper)."""
    mode = get_trading_mode()
    return {"mode": mode, "is_paper": mode == "paper"}


@router.put("/trading-mode")
async def update_trading_mode(body: SetTradingModeRequest):
    """
    Switch between live and paper trading modes.

    Paper mode uses real market data but simulates all order fills in-memory.
    The engine must be stopped before switching modes.
    """
    if body.mode not in ("live", "paper"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.mode}'. Must be 'live' or 'paper'.",
        )

    try:
        result = set_trading_mode(body.mode)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.get("/trading-mode/status")
async def get_trading_mode_status():
    """Get detailed paper trading status (capital, P&L, positions)."""
    mode = get_trading_mode()

    if mode != "paper":
        return {
            "mode": "live",
            "is_paper": False,
            "paper_status": None,
        }

    # Import here to avoid circular dependency
    from app.api.deps import get_provider
    try:
        provider = get_provider()
        from app.providers.paper.provider import PaperTradingProvider
        if isinstance(provider, PaperTradingProvider):
            return {
                "mode": "paper",
                "is_paper": True,
                "paper_status": provider.order_book.get_status(),
            }
    except Exception:
        pass

    return {
        "mode": "paper",
        "is_paper": True,
        "paper_status": None,
    }


@router.post("/trading-mode/reset")
async def reset_paper_trading():
    """Reset paper trading session (clear all orders/positions/trades, restore capital)."""
    mode = get_trading_mode()
    if mode != "paper":
        raise HTTPException(status_code=400, detail="Not in paper trading mode")

    from app.api.deps import get_provider
    try:
        provider = get_provider()
        from app.providers.paper.provider import PaperTradingProvider
        if isinstance(provider, PaperTradingProvider):
            provider.order_book.reset()
            return {"status": "reset", "paper_status": provider.order_book.get_status()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=500, detail="Paper provider not available")


# ── Risk Management ──────────────────────────────────────────


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


# ── Generic Config CRUD ──────────────────────────────────────
# IMPORTANT: The /{key} route MUST be last — it's a catch-all
# that would shadow any specific routes declared after it.


@router.get("/")
async def get_all_config(config: ConfigDep):
    """Get all configuration values (secrets are redacted)."""
    raw = config.get_all()
    return {k: _redact(k, v) for k, v in raw.items()}


@router.put("/")
async def set_config(body: SetConfigRequest, config: ConfigDep):
    config.set_db_override(body.key, body.value)
    return {"key": body.key, "value": body.value, "scope": body.scope}


@router.get("/{key}")
async def get_config(key: str, config: ConfigDep):
    try:
        value = config.get(key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")
    return {"key": key, "value": value}
