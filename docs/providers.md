# Providers

The platform uses a **provider abstraction** to support multiple brokers through a unified interface. All broker-specific logic is encapsulated behind the `BrokerProvider` abstract class.

## Provider Architecture

```
BrokerProvider (Abstract Base Class)
├── ZerodhaProvider  ─── Kite Connect SDK ─── Live Trading
└── MockProvider     ─── MockEngine         ─── Paper Trading
```

## Abstract Interface

`BrokerProvider` defines 20+ abstract methods that every provider must implement:

### Authentication
| Method | Description |
|--------|-------------|
| `get_login_url()` | OAuth redirect URL |
| `authenticate(request_token)` | Exchange token for session |
| `invalidate_session()` | Logout |

### Orders
| Method | Description |
|--------|-------------|
| `place_order(request)` | Place a new order, returns order_id |
| `modify_order(variety, order_id, params)` | Modify pending order |
| `cancel_order(variety, order_id)` | Cancel pending order |
| `get_orders()` | List all orders |
| `get_order_history(order_id)` | Status history for one order |
| `get_trades()` | List all fills/trades |
| `get_order_trades(order_id)` | Trades for one order |

### Portfolio
| Method | Description |
|--------|-------------|
| `get_positions()` | Net + day positions |
| `get_holdings()` | Long-term holdings |
| `get_margins(segment)` | Margin breakdown |

### Market Data
| Method | Description |
|--------|-------------|
| `get_quote(instruments)` | Full quotes |
| `get_ltp(instruments)` | Last traded prices |
| `get_ohlc(instruments)` | OHLC data |
| `get_historical(token, interval, from, to)` | Candle data |
| `get_instruments(exchange)` | Instrument master |

### WebSocket
| Method | Description |
|--------|-------------|
| `create_ticker()` | Create real-time tick connection |

## Provider Registry

The `registry.py` module manages the provider lifecycle:

```python
# Auto-discovery on startup
discover_providers()  # Scans for available providers

# Registration and activation
register_provider("zerodha", ZerodhaProvider)
set_active_provider("mock")
provider = get_active_provider()
```

### Discovery Process
1. On application startup, `discover_providers()` runs
2. It attempts to import each provider module
3. If dependencies are available (e.g., `kiteconnect` for Zerodha), the provider is registered
4. Missing dependencies log a warning but don't prevent startup

---

## Zerodha Provider

Wraps the [Kite Connect Python SDK](https://kiteconnect.zerodha.com/) (`kiteconnect` package).

### Authentication Flow
```
1. GET /api/auth/login-url
   → Returns Kite OAuth URL

2. User logs in at Zerodha
   → Redirected back with request_token

3. POST /api/auth/callback { request_token }
   → Exchanges for access_token via Kite API
   → Stores session
```

### Type Mapping

The `ZerodhaMapper` class converts between Kite's raw dictionaries and the platform's typed dataclasses:

| Kite Format | Platform Type |
|-------------|---------------|
| `kite.orders()` dict | `Order` dataclass |
| `kite.positions()` dict | `Position` dataclass |
| `kite.holdings()` dict | `Holding` dataclass |
| `kite.quote()` dict | `Quote` dataclass |
| Raw OHLCV list | `Candle` dataclass |
| Instrument CSV row | `Instrument` dataclass |

### Health Check
Calls `kite.profile()` and measures response latency.

### Configuration

```yaml
# config/providers/zerodha.yaml
zerodha:
  api_key: ""              # Set via TRADE_ZERODHA_API_KEY
  api_secret: ""           # Set via TRADE_ZERODHA_API_SECRET
  base_url: "https://api.kite.trade"
  ws_url: "wss://ws.kite.trade"
  timeout: 30              # Request timeout (seconds)
  max_retries: 3           # Retry on transient errors
  rate_limit_per_second: 10
```

### WebSocket Ticker

`ZerodhaTicker` wraps `KiteTicker` from the Kite SDK:
- Converts raw tick dicts to `TickData` via mapper
- Supports LTP, QUOTE, and FULL tick modes
- Auto-reconnects and re-subscribes on disconnect

---

## Mock Provider

In-memory paper trading engine for strategy testing without real money.

### Components
- **MockProvider**: Implements `BrokerProvider` interface
- **MockEngine**: Core simulation (order matching, fills, positions)
- **MockTicker**: Simulated WebSocket tick delivery
- **TimeController**: Session time management with VirtualClock
- **TickRecorder**: Record live ticks for later replay
- **TickReplayer**: Replay recorded tick data

### Order Simulation

```
place_order(OrderRequest)
    │
    ├─ MARKET order → Immediate fill at LTP ± slippage
    │
    └─ LIMIT/SL order → Added to pending queue
                             │
                             ├─ On each tick: check price conditions
                             │
                             └─ When triggered → Fill at trigger price ± slippage
```

### Fill Simulation
- **Slippage**: Configurable percentage (default 0.05% = 5 basis points)
  - BUY: `fill_price = ltp × (1 + slippage_pct / 100)`
  - SELL: `fill_price = ltp × (1 - slippage_pct / 100)`
- **Brokerage**: Flat fee per order (default ₹20)
- **Auto-fill**: MARKET orders fill instantly when `auto_fill_market_orders=true`

### Position Tracking
- Key format: `exchange:symbol:product` (e.g., `NSE:RELIANCE:CNC`)
- Tracks: quantity, average price, buy/sell breakdown, realized P&L
- Updates on every fill

### Capital Management
- Initial capital set when creating session
- Orders deduct from available capital
- Sells return capital
- Brokerage deducted per order

### Configuration

```yaml
# config/mock.yaml
mock:
  default_capital: 1000000.0
  slippage_pct: 0.05
  brokerage_per_order: 20.0
  speed_multiplier: 1.0
  auto_fill_market_orders: true
  realistic_fills: true
  market_hours_only: true
```

---

## Custom Exceptions

All providers throw typed exceptions:

| Exception | Meaning |
|-----------|---------|
| `ProviderError` | Base provider exception |
| `AuthenticationError` | Auth failure or expired session |
| `OrderError` | Order placement/modification failure |
| `DataError` | Market data retrieval failure |
| `ConnectionError` | Network/connectivity issue |
| `InsufficientFundsError` | Not enough margin/capital |
| `RateLimitError` | API rate limit exceeded |

## Adding a New Provider

1. Create a new module in `backend/app/providers/`
2. Implement `BrokerProvider` abstract class
3. Create a type mapper class
4. Register in `discover_providers()` or manually via `register_provider()`
5. Add YAML config in `config/providers/`
