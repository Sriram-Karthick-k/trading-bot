"""
Provider management routes.
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from app.providers.registry import (
    deactivate_provider,
    discover_providers,
    get_provider,
    get_active_provider,
    list_providers,
    set_active_provider,
)

router = APIRouter(prefix="/providers", tags=["providers"])


class ActivateRequest(BaseModel):
    provider_name: str
    config: dict = {}


@router.get("/")
async def get_providers():
    """List all registered providers."""
    providers = list_providers()
    result = []
    for name, info in providers.items():
        result.append({
            "name": info["name"],
            "display_name": info.get("display_name", name),
            "is_active": info.get("active", False),
            "supported_exchanges": info.get("supported_exchanges", []),
            "instantiated": info.get("instantiated", False),
        })
    return result


@router.post("/discover")
async def discover():
    """Discover and register available providers."""
    discover_providers()
    providers = list_providers()
    return {"discovered": list(providers.keys())}


@router.post("/activate")
async def activate_provider(body: ActivateRequest):
    """Set the active provider."""
    try:
        get_provider(body.provider_name)
        set_active_provider(body.provider_name)
        return {"active_provider": body.provider_name}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/active")
async def get_active():
    """Get the currently active provider."""
    try:
        provider = get_active_provider()
        info = provider.get_provider_info()
        return {
            "name": info.name,
            "display_name": info.display_name,
            "supported_exchanges": [e.value for e in info.supported_exchanges],
        }
    except Exception:
        return {"active_provider": None}


@router.post("/deactivate")
async def deactivate_active_provider():
    """Deactivate the currently active provider."""
    try:
        deactivate_provider()
        return {"status": "deactivated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{provider_name}/health")
async def provider_health(provider_name: str):
    try:
        provider = get_provider(provider_name)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    health = await provider.health_check()
    return {
        "healthy": health.healthy,
        "latency_ms": health.latency_ms,
        "message": health.message,
    }
