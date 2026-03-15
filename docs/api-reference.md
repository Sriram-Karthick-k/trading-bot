# API Reference

Base URL: `http://localhost:8000/api`

All endpoints return JSON. The frontend proxies `/api/*` requests to the backend automatically.

---

## Health

### `GET /api/health`
Returns system health and version info.

**Response:**
```json
{
  "status": "ok",
  "version": "0.1.0"
}
```

---

## Authentication

### `GET /api/auth/login-url`
Get the OAuth login URL for the active provider.

**Response:**
```json
{
  "login_url": "https://kite.zerodha.com/connect/login?...",
  "provider": "zerodha"
}
```

### `POST /api/auth/callback`
Exchange a request token for an access token.

**Body:**
```json
{
  "request_token": "abc123"
}
```

**Response:**
```json
{
  "user_id": "AB1234",
  "access_token": "token_value",
  "provider": "zerodha"
}
```

### `GET /api/auth/session`
Check current authentication status.

**Response:**
```json
{
  "authenticated": true,
  "user_id": "AB1234",
  "provider": "mock",
  "latency_ms": 12
}
```

---

## Orders

### `POST /api/orders/place`
Place a new order.

**Body:**
```json
{
  "exchange": "NSE",
  "trading_symbol": "RELIANCE",
  "transaction_type": "BUY",
  "order_type": "MARKET",
  "quantity": 10,
  "product": "CNC",
  "price": null,
  "trigger_price": null,
  "validity": "DAY",
  "variety": "regular",
  "tag": "my_tag"
}
```

**Required Fields:** `exchange`, `trading_symbol`, `transaction_type`, `order_type`, `quantity`, `product`

**Enum Values:**
- `exchange`: NSE, BSE, NFO, CDS, BCD, MCX, BFO, MF
- `transaction_type`: BUY, SELL
- `order_type`: MARKET, LIMIT, SL, SL-M
- `product`: CNC, NRML, MIS, MTF
- `variety`: regular, amo, co, iceberg, auction
- `validity`: DAY, IOC, TTL

**Response:**
```json
{
  "order_id": "250115000001"
}
```

### `GET /api/orders/`
List all orders for today.

**Response:**
```json
[
  {
    "order_id": "250115000001",
    "exchange": "NSE",
    "trading_symbol": "RELIANCE",
    "transaction_type": "BUY",
    "order_type": "MARKET",
    "quantity": 10,
    "filled_quantity": 10,
    "pending_quantity": 0,
    "price": 0,
    "average_price": 2450.50,
    "status": "COMPLETE",
    "status_message": "",
    "product": "CNC",
    "variety": "regular",
    "validity": "DAY",
    "order_timestamp": "2025-01-15T10:30:00",
    "exchange_timestamp": "2025-01-15T10:30:01",
    "tag": "my_tag"
  }
]
```

### `PUT /api/orders/{variety}/{order_id}`
Modify a pending order.

**Body:**
```json
{
  "quantity": 15,
  "price": 2440.00,
  "order_type": "LIMIT"
}
```

### `DELETE /api/orders/{variety}/{order_id}`
Cancel a pending order.

**Response:**
```json
{
  "order_id": "250115000001",
  "status": "cancelled"
}
```

### `GET /api/orders/managed`
List orders tracked by OrderManager (includes strategy context).

---

## Portfolio

### `GET /api/portfolio/positions`
Get open positions (net and day).

**Response:**
```json
{
  "net": [
    {
      "trading_symbol": "RELIANCE",
      "exchange": "NSE",
      "product": "CNC",
      "quantity": 10,
      "average_price": 2450.50,
      "last_price": 2460.00,
      "pnl": 95.00,
      "buy_quantity": 10,
      "sell_quantity": 0,
      "buy_price": 2450.50,
      "sell_price": 0,
      "buy_value": 24505.00,
      "sell_value": 0,
      "day_buy_quantity": 10,
      "day_sell_quantity": 0
    }
  ],
  "day": []
}
```

### `GET /api/portfolio/holdings`
Get long-term equity holdings.

**Response:**
```json
[
  {
    "trading_symbol": "INFY",
    "exchange": "NSE",
    "isin": "INE009A01021",
    "quantity": 50,
    "average_price": 1450.00,
    "last_price": 1520.30,
    "pnl": 3515.00,
    "day_change": 15.30,
    "day_change_percentage": 1.02
  }
]
```

### `GET /api/portfolio/margins`
Get margin details.

**Response:**
```json
{
  "equity": {
    "available": { "live_balance": 500000, "opening_balance": 500000, "collateral": 0 },
    "used": { "debits": 24505, "exposure": 0, "span": 0 },
    "net": 475495
  },
  "commodity": null
}
```

---

## Market Data

### `GET /api/market/quote?instruments=NSE:RELIANCE,NSE:INFY`
Get full quotes for instruments.

**Response:**
```json
{
  "NSE:RELIANCE": {
    "instrument_token": 256265,
    "last_price": 2460.00,
    "volume": 1234567,
    "buy_quantity": 50000,
    "sell_quantity": 45000,
    "ohlc": { "open": 2445, "high": 2470, "low": 2440, "close": 2450 },
    "change": 10.00,
    "last_trade_time": "2025-01-15T14:30:00"
  }
}
```

### `GET /api/market/ltp?instruments=NSE:RELIANCE`
Get last traded price only.

### `GET /api/market/ohlc?instruments=NSE:RELIANCE`
Get OHLC + LTP data.

### `GET /api/market/historical/{instrument_token}?interval=day&from_date=2025-01-01&to_date=2025-01-31`
Get historical OHLCV candles.

**Query Parameters:**
- `interval`: `minute`, `3minute`, `5minute`, `10minute`, `15minute`, `30minute`, `60minute`, `day`
- `from_date`: Start date (YYYY-MM-DD)
- `to_date`: End date (YYYY-MM-DD)

**Response:**
```json
[
  {
    "timestamp": "2025-01-15T00:00:00",
    "open": 2445.0,
    "high": 2470.0,
    "low": 2440.0,
    "close": 2460.0,
    "volume": 1234567
  }
]
```

### `GET /api/market/instruments?exchange=NSE`
Get instrument master data (max 1000 per request).

---

## Strategies

### `GET /api/strategies/`
List all active strategies.

**Response:**
```json
[
  {
    "strategy_id": "momentum_1",
    "name": "Momentum Breakout",
    "state": "running",
    "instruments": [256265, 341249],
    "params": { "lookback": 20, "threshold": 2.0 },
    "metrics": {
      "total_signals": 15,
      "total_trades": 8,
      "winning_trades": 5,
      "losing_trades": 3,
      "total_pnl": 12500.0,
      "max_drawdown": -3200.0
    }
  }
]
```

### `GET /api/strategies/types`
Get available strategy types and their parameter schemas.

### `GET /api/strategies/{id}`
Get state snapshot for a specific strategy.

### `POST /api/strategies/{id}/start`
Start a strategy.

### `POST /api/strategies/{id}/stop`
Stop a strategy.

### `POST /api/strategies/{id}/pause`
Pause a running strategy.

### `POST /api/strategies/{id}/resume`
Resume a paused strategy.

### `PUT /api/strategies/{id}/params`
Update strategy parameters.

**Body:**
```json
{
  "lookback": 30,
  "threshold": 1.5
}
```

### `DELETE /api/strategies/{id}`
Remove a strategy.

---

## Providers

### `GET /api/providers/`
List all registered providers.

**Response:**
```json
[
  {
    "name": "mock",
    "is_active": true,
    "is_instantiated": true,
    "provider_type": "MockProvider"
  },
  {
    "name": "zerodha",
    "is_active": false,
    "is_instantiated": false,
    "provider_type": "ZerodhaProvider"
  }
]
```

### `POST /api/providers/discover`
Auto-discover and register available providers.

### `POST /api/providers/activate`
Set the active provider.

**Body:**
```json
{
  "provider": "zerodha"
}
```

### `GET /api/providers/active`
Get the currently active provider.

### `GET /api/providers/{name}/health`
Health check for a specific provider.

**Response:**
```json
{
  "provider": "mock",
  "healthy": true,
  "latency_ms": 1.2,
  "message": "Mock provider operational"
}
```

---

## Configuration API

### `GET /api/config/`
Get all configuration (merged from all layers).

### `GET /api/config/{key}`
Get a specific config value.

### `PUT /api/config/`
Set a runtime override.

**Body:**
```json
{
  "key": "risk.max_daily_loss",
  "value": 75000
}
```

### `GET /api/config/risk/limits`
Get current risk limits.

### `PUT /api/config/risk/limits`
Update risk limits.

**Body:**
```json
{
  "max_order_value": 600000,
  "max_daily_loss": 75000,
  "kill_switch_active": false
}
```

### `GET /api/config/risk/status`
Real-time risk metrics.

**Response:**
```json
{
  "daily_loss": 12500.0,
  "daily_loss_limit": 50000.0,
  "daily_loss_pct": 25.0,
  "open_orders": 3,
  "open_positions": 2,
  "orders_last_minute": 5,
  "kill_switch_active": false
}
```

### `POST /api/config/risk/kill-switch/activate`
Activate emergency kill switch (blocks all new orders).

### `POST /api/config/risk/kill-switch/deactivate`
Deactivate kill switch.

---

## Mock Trading

### `POST /api/mock/session`
Create a paper trading session.

**Body:**
```json
{
  "capital": 500000,
  "start_date": "2025-01-01",
  "end_date": "2025-03-31"
}
```

### `GET /api/mock/session`
Get session status.

**Response:**
```json
{
  "session_id": "mock_session_1",
  "status": "active",
  "capital": 500000,
  "available_capital": 475000,
  "realized_pnl": 3500,
  "unrealized_pnl": 1200,
  "current_time": "2025-01-15T10:30:00",
  "open_positions": 2,
  "total_trades": 15,
  "progress": 0.17
}
```

### Time Controls

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/mock/time/set-date` | POST | Jump to specific date |
| `/api/mock/time/market-open` | POST | Advance to 09:15 |
| `/api/mock/time/market-close` | POST | Advance to 15:30 |
| `/api/mock/time/next-day` | POST | Move to next trading day (skips weekends) |
| `/api/mock/time/speed` | POST | Set speed multiplier `{ "speed": 10 }` |
| `/api/mock/time/pause` | POST | Pause time |
| `/api/mock/time/resume` | POST | Resume time |
| `/api/mock/reset` | POST | Clear all mock state |

### `GET /api/mock/orders`
List orders in mock session.

### `GET /api/mock/positions`
List positions in mock session.

---

## WebSocket

### `ws://localhost:8000/ws/ticks/{client_id}`
Real-time tick data stream.

**Subscribe Message:**
```json
{
  "action": "subscribe",
  "tokens": [256265, 341249]
}
```

**Unsubscribe Message:**
```json
{
  "action": "unsubscribe",
  "tokens": [256265]
}
```

**Tick Message (received):**
```json
{
  "instrument_token": 256265,
  "last_price": 2460.50,
  "volume": 1234567,
  "timestamp": "2025-01-15T14:30:00"
}
```

---

## Error Handling

All errors return standard JSON:

```json
{
  "detail": "Order value 600000 exceeds max_order_value 500000"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad Request — invalid parameters |
| 401 | Unauthorized — not authenticated |
| 403 | Forbidden — kill switch active |
| 404 | Not Found — resource doesn't exist |
| 422 | Validation Error — schema mismatch |
| 429 | Rate Limited — too many requests |
| 500 | Internal Error — server fault |
