"""
Provider registry and dependency injection.

Discovers, registers, and instantiates broker providers.
Provides FastAPI dependencies for route handlers.
"""

from __future__ import annotations

import logging
from typing import Any

from app.providers.base import BrokerProvider, ProviderError

logger = logging.getLogger(__name__)

# ─── Registry ─────────────────────────────────────────────────────────────────

_PROVIDER_CLASSES: dict[str, type[BrokerProvider]] = {}
_PROVIDER_INSTANCES: dict[str, BrokerProvider] = {}
_ACTIVE_PROVIDER: str | None = None


def register_provider(name: str, provider_class: type[BrokerProvider]) -> None:
    """Register a provider class by name."""
    _PROVIDER_CLASSES[name] = provider_class
    logger.info("Registered provider: %s -> %s", name, provider_class.__name__)


def get_provider_class(name: str) -> type[BrokerProvider]:
    """Get a registered provider class by name."""
    if name not in _PROVIDER_CLASSES:
        raise ProviderError(f"Provider '{name}' is not registered. Available: {list(_PROVIDER_CLASSES.keys())}")
    return _PROVIDER_CLASSES[name]


def create_provider(name: str, config: dict[str, Any] | None = None) -> BrokerProvider:
    """Create and cache a provider instance."""
    cls = get_provider_class(name)
    instance = cls(**(config or {}))
    _PROVIDER_INSTANCES[name] = instance
    logger.info("Created provider instance: %s", name)
    return instance


def get_provider(name: str) -> BrokerProvider:
    """Get a cached provider instance, or create one."""
    if name not in _PROVIDER_INSTANCES:
        return create_provider(name)
    return _PROVIDER_INSTANCES[name]


def set_active_provider(name: str) -> None:
    """Set the currently active provider."""
    global _ACTIVE_PROVIDER
    if name not in _PROVIDER_CLASSES:
        raise ProviderError(f"Cannot activate unregistered provider '{name}'")
    _ACTIVE_PROVIDER = name
    logger.info("Active provider set to: %s", name)


def get_active_provider() -> BrokerProvider:
    """Get the currently active provider instance."""
    if _ACTIVE_PROVIDER is None:
        raise ProviderError("No active provider set. Call set_active_provider() first.")
    return get_provider(_ACTIVE_PROVIDER)


def get_active_provider_name() -> str | None:
    """Get the name of the currently active provider."""
    return _ACTIVE_PROVIDER


def deactivate_provider() -> None:
    """Deactivate the currently active provider."""
    global _ACTIVE_PROVIDER
    if _ACTIVE_PROVIDER is None:
        raise ProviderError("No active provider to deactivate")
    logger.info("Deactivated provider: %s", _ACTIVE_PROVIDER)
    _ACTIVE_PROVIDER = None


def list_providers() -> dict[str, dict[str, Any]]:
    """List all registered providers with their status."""
    result = {}
    for name, cls in _PROVIDER_CLASSES.items():
        instance = _PROVIDER_INSTANCES.get(name)
        result[name] = {
            "name": name,
            "class": cls.__name__,
            "instantiated": instance is not None,
            "active": name == _ACTIVE_PROVIDER,
        }
        if instance:
            info = instance.get_provider_info()
            result[name]["display_name"] = info.display_name
            result[name]["supported_exchanges"] = [e.value for e in info.supported_exchanges]
    return result


def clear_registry() -> None:
    """Clear all registrations (for testing)."""
    global _ACTIVE_PROVIDER
    _PROVIDER_CLASSES.clear()
    _PROVIDER_INSTANCES.clear()
    _ACTIVE_PROVIDER = None


# ─── Auto-discovery ──────────────────────────────────────────────────────────


def discover_providers() -> None:
    """Auto-discover and register built-in providers."""
    try:
        from app.providers.zerodha.provider import ZerodhaProvider
        register_provider("zerodha", ZerodhaProvider)
    except ImportError:
        logger.warning("ZerodhaProvider not available (missing kiteconnect?)")

    try:
        from app.providers.mock.provider import MockProvider
        register_provider("mock", MockProvider)
    except ImportError:
        logger.warning("MockProvider not available")

    # Auto-activate default provider from env
    import os
    default = os.environ.get("TRADE_DEFAULT_PROVIDER")
    if default and default in _PROVIDER_CLASSES and _ACTIVE_PROVIDER is None:
        try:
            if default == "zerodha":
                api_key = os.environ.get("TRADE_ZERODHA_API_KEY", "")
                api_secret = os.environ.get("TRADE_ZERODHA_API_SECRET", "")
                if api_key:
                    create_provider("zerodha", {"api_key": api_key, "api_secret": api_secret})
            else:
                create_provider(default)
            set_active_provider(default)
            logger.info("Auto-activated default provider: %s", default)
        except Exception as e:
            logger.warning("Failed to auto-activate provider '%s': %s", default, e)
