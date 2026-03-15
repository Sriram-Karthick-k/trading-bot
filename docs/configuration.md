# Configuration Reference

The platform uses a **three-layer configuration system** where each layer can override the one below it.

## Resolution Hierarchy

```
Priority (High → Low)
──────────────────────
1. Database/UI Overrides    ← Runtime changes via API or Settings page
2. YAML Config Files        ← config/*.yaml (version-controlled)
3. Environment Variables    ← TRADE_* prefix
4. Schema Defaults          ← Hardcoded fallbacks in code
```

When a config value is requested, the system checks each layer in order and returns the first match.

---

## Environment Variables

All environment variables use the `TRADE_` prefix. Dot-notation config keys map to underscored env vars.

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADE_APP_DEBUG` | `false` | Enable debug mode |
| `TRADE_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TRADE_DATABASE_URL` | `postgresql+asyncpg://trade:trade@localhost:5432/zerodha_trade` | PostgreSQL connection string |
| `TRADE_REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `TRADE_DEFAULT_PROVIDER` | `mock` | Active broker provider (`mock` or `zerodha`) |
| `TRADE_ZERODHA_API_KEY` | _(empty)_ | Zerodha Kite Connect API key |
| `TRADE_ZERODHA_API_SECRET` | _(empty)_ | Zerodha Kite Connect API secret |
| `TRADE_MAX_DAILY_LOSS` | `50000` | Maximum allowed daily loss (₹) |
| `TRADE_KILL_SWITCH` | `false` | Emergency stop all trading |

### Frontend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | _(empty, uses proxy)_ | Backend API base URL |
| `NEXT_PUBLIC_WS_URL` | `ws://localhost:8000` | WebSocket URL for tick data |

---

## YAML Configuration Files

Located in `backend/config/`. All files are loaded at startup.

### config/default.yaml — Application Defaults

```yaml
app:
  name: "Zerodha Trade Platform"

provider:
  default: "mock"           # Default provider on startup
  auto_discover: true       # Auto-discover available providers

server:
  host: "0.0.0.0"           # Bind host
  port: 8000                # Bind port

database:
  url: "postgresql+asyncpg://trade:trade@localhost:5432/zerodha_trade"

redis:
  url: "redis://localhost:6379/0"
```

### config/risk.yaml — Risk Management Limits

```yaml
risk:
  max_order_value: 500000.0        # Max value per single order (₹)
  max_position_value: 1000000.0    # Max total position value (₹)
  max_loss_per_trade: 10000.0      # Max loss per individual trade (₹)
  max_daily_loss: 50000.0          # Max cumulative daily loss (₹)
  max_open_orders: 20              # Max concurrent open orders
  max_open_positions: 10           # Max concurrent open positions
  max_quantity_per_order: 5000     # Max quantity in single order
  max_orders_per_minute: 30        # Rate limit for order placement
  allowed_exchanges:               # Exchanges allowed for trading
    - NSE
    - BSE
    - NFO
    - MCX
    - CDS
    - BFO
  trading_hours:
    start: "09:15"                 # Market open time (IST)
    end: "15:30"                   # Market close time (IST)
  kill_switch: false               # Emergency stop (overridable via API)
```

### config/mock.yaml — Paper Trading Settings

```yaml
mock:
  default_capital: 1000000.0       # Starting capital for mock sessions (₹)
  slippage_pct: 0.05               # Simulated slippage percentage (0.05 = 5bp)
  brokerage_per_order: 20.0        # Flat brokerage per order (₹)
  speed_multiplier: 1.0            # Time speed (1.0 = real-time, 10.0 = 10x)
  auto_fill_market_orders: true    # Instantly fill MARKET orders
  realistic_fills: true            # Apply slippage to fill prices
  market_hours_only: true          # Only process orders during market hours
```

### config/providers/zerodha.yaml — Zerodha API Settings

```yaml
zerodha:
  api_key: ""                      # Kite Connect API key (use env var instead)
  api_secret: ""                   # Kite Connect API secret (use env var)
  base_url: "https://api.kite.trade"   # Kite API base URL
  ws_url: "wss://ws.kite.trade"        # Kite WebSocket URL
  timeout: 30                          # API request timeout (seconds)
  max_retries: 3                       # Max retries on transient failures
  rate_limit_per_second: 10            # API rate limit
```

---

## Overridable Config Keys (Schema Registry)

These keys are registered in `ConfigManager._SCHEMA_REGISTRY` and can be overridden at runtime via the API or Settings page.

### Risk Configuration

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `risk.max_order_value` | float | 500000 | 0 | — | Max value per order |
| `risk.max_position_value` | float | 1000000 | 0 | — | Max total position value |
| `risk.max_daily_loss` | float | 50000 | 0 | — | Max daily cumulative loss |
| `risk.max_open_orders` | int | 20 | 1 | — | Max concurrent open orders |
| `risk.max_open_positions` | int | 10 | 1 | — | Max concurrent positions |
| `risk.max_quantity_per_order` | int | 5000 | 1 | — | Max quantity per order |
| `risk.max_orders_per_minute` | int | 30 | 1 | — | Order rate limit |
| `risk.kill_switch_active` | bool | false | — | — | Emergency stop toggle |

### Mock Configuration

| Key | Type | Default | Min | Max | Description |
|-----|------|---------|-----|-----|-------------|
| `mock.default_capital` | float | 1000000 | 0 | — | Default starting capital |
| `mock.slippage_pct` | float | 0.05 | 0 | 1.0 | Fill slippage percentage |
| `mock.brokerage_per_order` | float | 20.0 | 0 | — | Brokerage charge per order |

### Provider Configuration

| Key | Type | Default | Allowed Values | Description |
|-----|------|---------|----------------|-------------|
| `provider.active` | str | "mock" | mock, zerodha | Active broker provider |
| `provider.auto_discover` | bool | true | — | Auto-discover providers on startup |

---

## Runtime Configuration API

### Get All Configuration
```
GET /api/config/
```

### Get Specific Key
```
GET /api/config/{key}
```

### Set Runtime Override
```
PUT /api/config/
Body: { "key": "risk.max_daily_loss", "value": 75000 }
```

### Risk Limits
```
GET  /api/config/risk/limits       # Get current risk limits
PUT  /api/config/risk/limits       # Update risk limits
GET  /api/config/risk/status       # Real-time risk metrics
POST /api/config/risk/kill-switch/activate
POST /api/config/risk/kill-switch/deactivate
```

---

## Configuration Precedence Example

For `risk.max_daily_loss`:

```
1. DB Override:  PUT /api/config/ { "key": "risk.max_daily_loss", "value": 75000 }
                 → Returns 75000

2. YAML (config/risk.yaml):  max_daily_loss: 50000
                 → Returns 50000 (if no DB override)

3. Environment:  TRADE_MAX_DAILY_LOSS=25000
                 → Returns 25000 (if no YAML or DB override)

4. Schema Default:  50000
                 → Returns 50000 (absolute fallback)
```

## Change Audit Trail

Every config change creates a `ConfigChangeEvent` with:
- Key that changed
- Old value → New value
- Timestamp
- Source layer (db, yaml, env)

The `ConfigAuditLog` database table stores the full history of all configuration changes.
