"""
Three-layer configuration manager.

Resolution order (highest priority wins):
1. DB/UI overrides (runtime changes via dashboard)
2. YAML config files (version-controlled defaults)
3. Environment variables
4. Hardcoded code defaults

Config keys use dot-notation: e.g., 'risk.max_daily_loss', 'strategy.momentum.ema_fast'
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar, get_origin

import yaml
from pydantic import BaseModel

T = TypeVar("T")

# Project root config directory
CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"


class ConfigSchema(BaseModel):
    """Schema definition for a single config key."""
    key: str
    description: str
    default: Any
    type: str  # "int", "float", "str", "bool", "list", "dict"
    min_value: float | None = None
    max_value: float | None = None
    enum_values: list[str] | None = None
    required: bool = False
    scope: str = "global"  # global | strategy | provider | mock


class ConfigChangeEvent(BaseModel):
    """Records a config change for audit logging."""
    key: str
    old_value: Any
    new_value: Any
    source: str  # "db", "yaml", "env", "default"
    changed_by: str = "system"
    scope: str = "global"


# ─── Config Registry ─────────────────────────────────────────────────────────

# All known config keys and their schemas.
# Strategies and modules register their config keys here.
_SCHEMA_REGISTRY: dict[str, ConfigSchema] = {}


def register_config(schema: ConfigSchema) -> None:
    """Register a config key with its schema."""
    _SCHEMA_REGISTRY[schema.key] = schema


def get_schema(key: str) -> ConfigSchema | None:
    """Get the schema for a config key."""
    return _SCHEMA_REGISTRY.get(key)


def get_all_schemas() -> dict[str, ConfigSchema]:
    """Get all registered config schemas."""
    return dict(_SCHEMA_REGISTRY)


# ─── Config Manager ──────────────────────────────────────────────────────────


class ConfigManager:
    """
    Resolves config values across three layers.

    Usage:
        config = ConfigManager()
        max_loss = config.get("risk.max_daily_loss", float, default=5000.0)
    """

    def __init__(
        self,
        yaml_dir: Path | None = None,
        db_getter: Any | None = None,
    ):
        self._yaml_dir = yaml_dir or CONFIG_DIR
        self._yaml_cache: dict[str, Any] = {}
        self._db_getter = db_getter  # Async callable: (key, scope) -> value | None
        self._db_cache: dict[str, Any] = {}
        self._change_listeners: list[Any] = []
        self._loaded = False

    def load_yaml_configs(self) -> None:
        """Load all YAML config files into cache."""
        self._yaml_cache.clear()
        if not self._yaml_dir.exists():
            self._loaded = True
            return

        for yaml_file in self._yaml_dir.rglob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    # Derive prefix from relative path
                    rel = yaml_file.relative_to(self._yaml_dir)
                    prefix = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
                    if prefix == "default":
                        # default.yaml keys go to root
                        self._flatten_dict(data, "", self._yaml_cache)
                    else:
                        self._flatten_dict(data, prefix, self._yaml_cache)
            except (yaml.YAMLError, OSError):
                continue
        self._loaded = True

    def _flatten_dict(self, d: dict, prefix: str, target: dict) -> None:
        """Flatten nested dict into dot-notation keys."""
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                self._flatten_dict(value, full_key, target)
            else:
                target[full_key] = value

    def get(self, key: str, type_hint: type[T] = str, default: T | None = None, scope: str = "global") -> T:  # type: ignore[assignment]
        """
        Get a config value, resolving across all layers.

        Priority: DB override > YAML file > Environment variable > default
        """
        if not self._loaded:
            self.load_yaml_configs()

        # Layer 1: DB/UI override (check cache first)
        cache_key = f"{scope}:{key}" if scope != "global" else key
        if cache_key in self._db_cache:
            return self._cast(self._db_cache[cache_key], type_hint)

        # Layer 2: YAML config files
        if key in self._yaml_cache:
            return self._cast(self._yaml_cache[key], type_hint)

        # Layer 3: Environment variable
        # Convert dot-notation to env var: risk.max_daily_loss -> TRADE_RISK_MAX_DAILY_LOSS
        env_key = "TRADE_" + key.upper().replace(".", "_")
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return self._cast(env_val, type_hint)

        # Layer 4: Schema default
        schema = _SCHEMA_REGISTRY.get(key)
        if schema is not None and schema.default is not None:
            return self._cast(schema.default, type_hint)

        # Layer 5: Provided default
        if default is not None:
            return default

        raise KeyError(f"Config key '{key}' not found in any layer and no default provided")

    async def get_async(self, key: str, type_hint: type[T] = str, default: T | None = None, scope: str = "global") -> T:  # type: ignore[assignment]
        """Async version that checks DB layer."""
        if not self._loaded:
            self.load_yaml_configs()

        # Layer 1: DB override
        if self._db_getter:
            db_val = await self._db_getter(key, scope)
            if db_val is not None:
                return self._cast(db_val, type_hint)

        # Fall through to sync resolution
        return self.get(key, type_hint, default, scope)

    def set_db_override(self, key: str, value: Any, scope: str = "global") -> ConfigChangeEvent:
        """
        Set a DB/UI override (highest priority).
        Returns a change event for audit logging.
        """
        # Validate against schema
        schema = _SCHEMA_REGISTRY.get(key)
        if schema:
            self._validate(key, value, schema)

        cache_key = f"{scope}:{key}" if scope != "global" else key
        old_value = self._db_cache.get(cache_key)
        self._db_cache[cache_key] = value

        event = ConfigChangeEvent(
            key=key,
            old_value=old_value,
            new_value=value,
            source="db",
            scope=scope,
        )

        for listener in self._change_listeners:
            listener(event)

        return event

    def remove_db_override(self, key: str, scope: str = "global") -> bool:
        """Remove a DB override, falling back to lower layers."""
        cache_key = f"{scope}:{key}" if scope != "global" else key
        if cache_key in self._db_cache:
            del self._db_cache[cache_key]
            return True
        return False

    def on_change(self, listener: Any) -> None:
        """Register a callback for config changes."""
        self._change_listeners.append(listener)

    def get_resolved_source(self, key: str, scope: str = "global") -> str:
        """Return which layer a config value comes from."""
        cache_key = f"{scope}:{key}" if scope != "global" else key
        if cache_key in self._db_cache:
            return "db"
        if key in self._yaml_cache:
            return "yaml"
        env_key = "TRADE_" + key.upper().replace(".", "_")
        if os.environ.get(env_key) is not None:
            return "env"
        if key in _SCHEMA_REGISTRY:
            return "default"
        return "unknown"

    def get_all(self, prefix: str = "") -> dict[str, Any]:
        """Get all config values under a prefix."""
        result: dict[str, Any] = {}
        # Merge all layers (lower priority first)
        for key, schema in _SCHEMA_REGISTRY.items():
            if key.startswith(prefix):
                try:
                    result[key] = self.get(key, default=schema.default)
                except KeyError:
                    pass
        for key, value in self._yaml_cache.items():
            if key.startswith(prefix):
                result[key] = value
        for key, value in self._db_cache.items():
            if key.startswith(prefix):
                result[key] = value
        return result

    def _validate(self, key: str, value: Any, schema: ConfigSchema) -> None:
        """Validate a value against its schema."""
        if schema.min_value is not None and isinstance(value, (int, float)):
            if value < schema.min_value:
                raise ValueError(
                    f"Config '{key}' value {value} is below minimum {schema.min_value}"
                )
        if schema.max_value is not None and isinstance(value, (int, float)):
            if value > schema.max_value:
                raise ValueError(
                    f"Config '{key}' value {value} is above maximum {schema.max_value}"
                )
        if schema.enum_values is not None:
            if str(value) not in schema.enum_values:
                raise ValueError(
                    f"Config '{key}' value '{value}' not in allowed values: {schema.enum_values}"
                )

    def _cast(self, value: Any, type_hint: type[T]) -> T:
        """Cast a value to the requested type."""
        if value is None:
            return value  # type: ignore[return-value]

        origin = get_origin(type_hint)
        if origin is not None:
            # Handle generic types (list[str], dict[str, int], etc.)
            return value  # type: ignore[return-value]

        if type_hint is bool:
            if isinstance(value, str):
                return value.lower() in ("true", "1", "yes", "on")  # type: ignore[return-value]
            return bool(value)  # type: ignore[return-value]

        if type_hint is int:
            return int(float(value)) if isinstance(value, str) else int(value)  # type: ignore[return-value]

        if type_hint is float:
            return float(value)  # type: ignore[return-value]

        if type_hint is str:
            return str(value)  # type: ignore[return-value]

        return value  # type: ignore[return-value]

    def reload(self) -> None:
        """Reload YAML configs from disk."""
        self._loaded = False
        self.load_yaml_configs()


# ─── Default Config Registrations ─────────────────────────────────────────────
# Core platform config keys. Strategies register their own keys.

_DEFAULT_SCHEMAS = [
    ConfigSchema(key="provider.active", description="Currently active provider name", default="zerodha", type="str", enum_values=["zerodha", "mock"]),
    ConfigSchema(key="risk.max_daily_loss", description="Maximum daily loss in INR before halting", default=5000.0, type="float", min_value=0),
    ConfigSchema(key="risk.max_daily_loss_pct", description="Maximum daily loss as % of capital", default=3.0, type="float", min_value=0, max_value=100),
    ConfigSchema(key="risk.risk_per_trade_pct", description="Max risk per trade as % of capital", default=1.0, type="float", min_value=0.1, max_value=10),
    ConfigSchema(key="risk.max_position_value", description="Max value of a single position in INR", default=500000.0, type="float", min_value=0),
    ConfigSchema(key="risk.max_open_orders", description="Maximum simultaneous open orders", default=10, type="int", min_value=1, max_value=100),
    ConfigSchema(key="risk.max_positions", description="Maximum simultaneous open positions", default=5, type="int", min_value=1, max_value=50),
    ConfigSchema(key="risk.default_sl_pct", description="Default stop-loss percentage", default=1.0, type="float", min_value=0.1, max_value=20),
    ConfigSchema(key="risk.trailing_sl_enabled", description="Enable trailing stop-loss", default=False, type="bool"),
    ConfigSchema(key="risk.cooldown_minutes", description="Cooldown after daily loss breach (minutes)", default=0, type="int", min_value=0),
    ConfigSchema(key="mock.default_slippage_pct", description="Default slippage % for mock fills", default=0.05, type="float", min_value=0, max_value=5),
    ConfigSchema(key="mock.default_capital", description="Default starting capital for mock sessions", default=100000.0, type="float", min_value=1000),
    ConfigSchema(key="mock.fill_latency_ms", description="Simulated fill latency in ms", default=50, type="int", min_value=0),
    ConfigSchema(key="mock.brokerage_per_order", description="Simulated brokerage per order in INR", default=20.0, type="float", min_value=0),
    ConfigSchema(key="scheduler.instrument_download_time", description="Time to download instruments (HH:MM)", default="08:30", type="str"),
    ConfigSchema(key="scheduler.strategy_start_time", description="Time to start strategies (HH:MM)", default="09:15", type="str"),
    ConfigSchema(key="scheduler.square_off_time", description="Time to auto-square-off MIS (HH:MM)", default="15:15", type="str"),
    ConfigSchema(key="scheduler.strategy_stop_time", description="Time to stop strategies (HH:MM)", default="15:30", type="str"),
    ConfigSchema(key="notifications.telegram_enabled", description="Enable Telegram notifications", default=False, type="bool"),
    ConfigSchema(key="notifications.email_enabled", description="Enable email notifications", default=False, type="bool"),
]

for _schema in _DEFAULT_SCHEMAS:
    register_config(_schema)
