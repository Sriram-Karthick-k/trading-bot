"""
Strategy management routes.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.api.deps import get_strategies
from app.strategies.base import Strategy

router = APIRouter(prefix="/strategies", tags=["strategies"])

# ── Strategy type registry ──────────────────────────────

_STRATEGY_CLASSES: dict[str, type[Strategy]] = {}


def _discover_strategy_types() -> None:
    """Import and register all built-in strategy types."""
    if _STRATEGY_CLASSES:
        return
    try:
        from app.strategies.sma_crossover import SMAcrossoverStrategy
        _STRATEGY_CLASSES[SMAcrossoverStrategy.name()] = SMAcrossoverStrategy
    except ImportError:
        pass
    try:
        from app.strategies.rsi_strategy import RSIStrategy
        _STRATEGY_CLASSES[RSIStrategy.name()] = RSIStrategy
    except ImportError:
        pass


class CreateStrategyRequest(BaseModel):
    strategy_type: str
    strategy_id: str
    params: dict = {}


class UpdateParamsRequest(BaseModel):
    params: dict


@router.get("/")
async def list_strategies():
    strategies = get_strategies()
    return [s.get_state_snapshot() for s in strategies.values()]


@router.get("/types")
async def list_strategy_types():
    """Return available strategy types and their parameter schemas."""
    _discover_strategy_types()
    result = []
    for name, cls in _STRATEGY_CLASSES.items():
        result.append({
            "name": name,
            "description": cls.description(),
            "params_schema": [
                {
                    "name": p.name,
                    "type": p.param_type.value,
                    "default": p.default,
                    "label": p.label,
                    "description": p.description,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "enum_values": p.enum_values,
                    "required": p.required,
                }
                for p in cls.get_params_schema()
            ],
        })
    return result


@router.post("/")
async def create_strategy(body: CreateStrategyRequest):
    """Create a new strategy instance."""
    _discover_strategy_types()
    cls = _STRATEGY_CLASSES.get(body.strategy_type)
    if not cls:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown strategy type: '{body.strategy_type}'. "
                   f"Available: {list(_STRATEGY_CLASSES.keys())}",
        )

    strategies = get_strategies()
    if body.strategy_id in strategies:
        raise HTTPException(status_code=409, detail=f"Strategy '{body.strategy_id}' already exists")

    # Fill defaults for missing params
    schema = cls.get_params_schema()
    params = dict(body.params)
    for pdef in schema:
        if pdef.name not in params and pdef.default is not None:
            params[pdef.name] = pdef.default

    instance = cls(strategy_id=body.strategy_id, params=params)
    errors = instance.validate_params()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})

    strategies[body.strategy_id] = instance
    return instance.get_state_snapshot()


@router.get("/{strategy_id}")
async def get_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return strategy.get_state_snapshot()


@router.post("/{strategy_id}/start")
async def start_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await strategy.start()
    return {"status": "started", "strategy_id": strategy_id}


@router.post("/{strategy_id}/stop")
async def stop_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    await strategy.stop()
    return {"status": "stopped", "strategy_id": strategy_id}


@router.post("/{strategy_id}/pause")
async def pause_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.pause()
    return {"status": "paused", "strategy_id": strategy_id}


@router.post("/{strategy_id}/resume")
async def resume_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.resume()
    return {"status": "running", "strategy_id": strategy_id}


@router.put("/{strategy_id}/params")
async def update_params(strategy_id: str, body: UpdateParamsRequest):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    strategy.params.update(body.params)
    errors = strategy.validate_params()
    if errors:
        raise HTTPException(status_code=400, detail={"validation_errors": errors})
    return {"status": "updated", "params": strategy.params}


@router.delete("/{strategy_id}")
async def delete_strategy(strategy_id: str):
    strategies = get_strategies()
    strategy = strategies.get(strategy_id)
    if not strategy:
        raise HTTPException(status_code=404, detail="Strategy not found")
    if strategy.state.value == "running":
        await strategy.stop()
    del strategies[strategy_id]
    return {"status": "deleted", "strategy_id": strategy_id}
