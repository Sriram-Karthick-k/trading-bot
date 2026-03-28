"""
Configuration management routes.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import ConfigDep, RiskDep, get_trading_mode, set_trading_mode
from app.core.risk_manager import RiskLimits
from app.db.database import async_session_factory
from app.models.models import ConfigEntry

from sqlalchemy import select

logger = logging.getLogger(__name__)

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


class PaperSettingsRequest(BaseModel):
    initial_capital: float | None = None
    slippage_pct: float | None = None
    brokerage_per_order: float | None = None


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

    # Persist to DB so mode survives restarts
    await _persist_trading_mode(body.mode)

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


@router.get("/paper-settings")
async def get_paper_settings():
    """Get paper trading settings (capital, slippage, brokerage)."""
    saved = await load_paper_settings_from_db()
    defaults = {
        "initial_capital": 1_000_000.0,
        "slippage_pct": 0.05,
        "brokerage_per_order": 20.0,
    }
    if saved:
        defaults.update(saved)
    return defaults


@router.put("/paper-settings")
async def update_paper_settings(body: PaperSettingsRequest):
    """
    Update paper trading settings.

    These are persisted to DB and applied when PaperTradingProvider is created.
    If paper mode is active, the provider must be recreated (mode switch) to apply changes.
    """
    settings: dict[str, float] = {}
    if body.initial_capital is not None:
        if body.initial_capital < 1000:
            raise HTTPException(status_code=400, detail="Capital must be at least 1,000")
        settings["initial_capital"] = body.initial_capital
    if body.slippage_pct is not None:
        if body.slippage_pct < 0 or body.slippage_pct > 5:
            raise HTTPException(status_code=400, detail="Slippage must be between 0% and 5%")
        settings["slippage_pct"] = body.slippage_pct
    if body.brokerage_per_order is not None:
        if body.brokerage_per_order < 0:
            raise HTTPException(status_code=400, detail="Brokerage cannot be negative")
        settings["brokerage_per_order"] = body.brokerage_per_order

    if not settings:
        raise HTTPException(status_code=400, detail="No settings provided")

    await _persist_paper_settings(settings)
    return {"status": "updated", "settings": settings}


# ── Trading Mode DB Persistence ──────────────────────────────

_TRADING_MODE_KEY = "trading.mode"


async def _persist_trading_mode(mode: str) -> None:
    """Write current trading mode to ConfigEntry DB table."""
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ConfigEntry).where(ConfigEntry.key == _TRADING_MODE_KEY)
            )
            entry = result.scalar_one_or_none()
            if entry:
                entry.value = mode
                entry.value_type = "str"
                entry.scope = "global"
                entry.updated_by = "api"
            else:
                entry = ConfigEntry(
                    key=_TRADING_MODE_KEY,
                    value=mode,
                    value_type="str",
                    scope="global",
                    description="Trading mode: live or paper",
                    updated_by="api",
                )
                session.add(entry)
            await session.commit()
        logger.info("Trading mode persisted to DB: %s", mode)
    except Exception as e:
        logger.warning("Failed to persist trading mode to DB: %s", e)


async def load_trading_mode_from_db() -> str | None:
    """
    Load persisted trading mode from the ConfigEntry DB table.

    Returns 'live' or 'paper' if found, or None if DB is empty / unavailable.
    """
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ConfigEntry).where(ConfigEntry.key == _TRADING_MODE_KEY)
            )
            entry = result.scalar_one_or_none()
            if entry and entry.value in ("live", "paper"):
                logger.info("Loaded trading mode from DB: %s", entry.value)
                return entry.value
            return None
    except Exception as e:
        logger.warning("Failed to load trading mode from DB: %s", e)
        return None


# ── Paper Settings DB Persistence ────────────────────────────

_PAPER_SETTINGS_FIELDS: dict[str, tuple[str, str]] = {
    "initial_capital": ("paper.initial_capital", "float"),
    "slippage_pct": ("paper.slippage_pct", "float"),
    "brokerage_per_order": ("paper.brokerage_per_order", "float"),
}


async def _persist_paper_settings(settings: dict[str, float]) -> None:
    """Write paper trading settings to ConfigEntry DB table."""
    try:
        async with async_session_factory() as session:
            for field_name, value in settings.items():
                if field_name not in _PAPER_SETTINGS_FIELDS:
                    continue
                config_key, value_type = _PAPER_SETTINGS_FIELDS[field_name]
                result = await session.execute(
                    select(ConfigEntry).where(ConfigEntry.key == config_key)
                )
                entry = result.scalar_one_or_none()
                if entry:
                    entry.value = str(value)
                    entry.value_type = value_type
                    entry.scope = "global"
                    entry.updated_by = "api"
                else:
                    entry = ConfigEntry(
                        key=config_key,
                        value=str(value),
                        value_type=value_type,
                        scope="global",
                        description=f"Paper trading: {field_name}",
                        updated_by="api",
                    )
                    session.add(entry)
            await session.commit()
        logger.info("Paper settings persisted to DB: %s", settings)
    except Exception as e:
        logger.warning("Failed to persist paper settings to DB: %s", e)


async def load_paper_settings_from_db() -> dict[str, float] | None:
    """
    Load persisted paper trading settings from the ConfigEntry DB table.

    Returns a dict with available settings, or None if DB is empty / unavailable.
    """
    try:
        async with async_session_factory() as session:
            config_keys = [key for key, _ in _PAPER_SETTINGS_FIELDS.values()]
            result = await session.execute(
                select(ConfigEntry).where(ConfigEntry.key.in_(config_keys))
            )
            entries = {row.key: row for row in result.scalars().all()}

            if not entries:
                return None

            settings: dict[str, float] = {}
            for field_name, (config_key, _) in _PAPER_SETTINGS_FIELDS.items():
                if config_key in entries:
                    settings[field_name] = float(entries[config_key].value)
            logger.info("Loaded %d paper setting(s) from DB", len(settings))
            return settings if settings else None
    except Exception as e:
        logger.warning("Failed to load paper settings from DB: %s", e)
        return None


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

    # Persist to DB so limits survive restarts
    await _persist_risk_limits(limits)

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


# ── Risk Limit DB Persistence ────────────────────────────────

# Mapping of RiskLimits field names → config key + value type
_RISK_LIMIT_FIELDS: dict[str, tuple[str, str]] = {
    "max_order_value": ("risk.max_order_value", "float"),
    "max_position_value": ("risk.max_position_value", "float"),
    "max_loss_per_trade": ("risk.max_loss_per_trade", "float"),
    "max_daily_loss": ("risk.max_daily_loss", "float"),
    "max_open_orders": ("risk.max_open_orders", "int"),
    "max_open_positions": ("risk.max_open_positions", "int"),
    "max_quantity_per_order": ("risk.max_quantity_per_order", "int"),
    "max_orders_per_minute": ("risk.max_orders_per_minute", "int"),
}


async def _persist_risk_limits(limits: RiskLimits) -> None:
    """Write current risk limits to ConfigEntry DB table."""
    try:
        async with async_session_factory() as session:
            for field_name, (config_key, value_type) in _RISK_LIMIT_FIELDS.items():
                value = str(getattr(limits, field_name))
                # Upsert: find existing or create new
                result = await session.execute(
                    select(ConfigEntry).where(ConfigEntry.key == config_key)
                )
                entry = result.scalar_one_or_none()
                if entry:
                    entry.value = value
                    entry.value_type = value_type
                    entry.scope = "global"
                    entry.updated_by = "api"
                else:
                    entry = ConfigEntry(
                        key=config_key,
                        value=value,
                        value_type=value_type,
                        scope="global",
                        description=f"Risk limit: {field_name}",
                        updated_by="api",
                    )
                    session.add(entry)
            await session.commit()
        logger.info("Risk limits persisted to DB")
    except Exception as e:
        logger.warning("Failed to persist risk limits to DB: %s", e)


async def load_risk_limits_from_db() -> RiskLimits | None:
    """
    Load persisted risk limits from the ConfigEntry DB table.

    Returns a RiskLimits object if any were found, or None if DB is
    empty / unavailable.
    """
    try:
        async with async_session_factory() as session:
            config_keys = [key for key, _ in _RISK_LIMIT_FIELDS.values()]
            result = await session.execute(
                select(ConfigEntry).where(ConfigEntry.key.in_(config_keys))
            )
            entries = {row.key: row for row in result.scalars().all()}

            if not entries:
                return None

            limits = RiskLimits()
            for field_name, (config_key, value_type) in _RISK_LIMIT_FIELDS.items():
                if config_key in entries:
                    raw = entries[config_key].value
                    if value_type == "float":
                        setattr(limits, field_name, float(raw))
                    elif value_type == "int":
                        setattr(limits, field_name, int(float(raw)))
            logger.info("Loaded %d risk limit(s) from DB", len(entries))
            return limits
    except Exception as e:
        logger.warning("Failed to load risk limits from DB: %s", e)
        return None


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
