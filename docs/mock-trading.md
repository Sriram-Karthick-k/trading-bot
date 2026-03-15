# Mock Trading Engine

The mock trading engine provides a complete paper trading environment for testing strategies and learning without risking real money.

## Overview

The mock system simulates:
- **Order matching and fills** with configurable slippage
- **Brokerage charges** (flat fee per order)
- **Position tracking** with real-time P&L
- **Capital management** (available margin, buying power)
- **Time simulation** via VirtualClock (fast-forward, pause, replay)
- **Market hour enforcement** (9:15 AM – 3:30 PM IST)

## Components

### MockProvider
Implements the full `BrokerProvider` interface using in-memory state. All orders, positions, and trades exist only in memory.

### MockEngine
Core simulation engine that handles:
- Order placement and matching
- Fill simulation with slippage
- Position tracking and P&L calculation
- Capital management
- Pending order monitoring on each tick

### VirtualClock
Pluggable time abstraction that allows:

| Method | Description |
|--------|-------------|
| `set_time(dt)` | Jump to specific timestamp |
| `advance(delta)` | Add a time duration |
| `set_speed(float)` | Speed multiplier (1.0 = real-time, 10.0 = 10x fast) |
| `pause()` | Freeze time |
| `resume()` | Unfreeze time |
| `tick()` | Advance based on elapsed real time × speed |
| `is_market_open()` | Check if virtual time is within market hours |

### TimeController
Higher-level session management wrapping VirtualClock:

| Method | Description |
|--------|-------------|
| `set_date_range(start, end)` | Set simulation period |
| `advance_to_market_open()` | Jump to 09:15 |
| `advance_to_market_close()` | Jump to 15:30 |
| `advance_to_next_trading_day()` | Skip to next weekday |
| `is_market_hours()` | Check within 09:15–15:30 |
| `get_progress()` | 0.0–1.0 completion ratio |
| `seek(target)` | Jump to any timestamp |

## Session Management

### Creating a Session

```
POST /api/mock/session
{
  "capital": 500000,
  "start_date": "2025-01-01",
  "end_date": "2025-03-31"
}
```

This:
1. Initializes MockEngine with the given capital
2. Sets VirtualClock to the start date
3. Configures TimeController date range

### Session Status

```
GET /api/mock/session
```

Returns:
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

## Order Simulation

### Market Orders
When `auto_fill_market_orders=true` (default):
1. Order is created with status `OPEN`
2. Immediately filled at LTP ± slippage
3. Trade record created
4. Position updated
5. Capital adjusted (order value + brokerage)

### Limit Orders
1. Order is created with status `OPEN`
2. Added to pending queue
3. On each tick, engine checks: `tick_price <= limit_price` (BUY) or `tick_price >= limit_price` (SELL)
4. When triggered, filled at limit price ± slippage

### Stop-Loss Orders
1. Order created with status `OPEN`
2. Added to pending queue
3. On each tick: `tick_price >= trigger_price` (BUY SL) or `tick_price <= trigger_price` (SELL SL)
4. When triggered, becomes a market/limit order and fills

## Fill Simulation

### Slippage Model
Configurable via `mock.slippage_pct` (default 0.05%):

```
BUY:  fill_price = ltp × (1 + slippage_pct / 100)
SELL: fill_price = ltp × (1 - slippage_pct / 100)
```

For LTP = ₹2,000 and slippage = 0.05%:
- BUY fills at ₹2,001 (₹1 slippage)
- SELL fills at ₹1,999 (₹1 slippage)

### Brokerage
Flat fee per order (default ₹20):
```
available_capital -= (order_value + brokerage_per_order)
```

## Time Controls (API)

| Action | Endpoint | Description |
|--------|----------|-------------|
| Set Date | `POST /mock/time/set-date` | Jump to `{ "date": "2025-02-01" }` |
| Market Open | `POST /mock/time/market-open` | Jump to 09:15 |
| Market Close | `POST /mock/time/market-close` | Jump to 15:30 |
| Next Day | `POST /mock/time/next-day` | Skip to next weekday 09:15 |
| Set Speed | `POST /mock/time/speed` | Set `{ "speed": 10 }` multiplier |
| Pause | `POST /mock/time/pause` | Freeze time |
| Resume | `POST /mock/time/resume` | Unfreeze time |
| Reset | `POST /mock/reset` | Clear all state |

## Tick Recording & Replay

### TickRecorder
Records live ticks from a real provider for later replay:
- Filters by instrument tokens
- Serializes each tick with sequence number and timestamp
- Output format: JSON array of `RecordedTickEntry`

### TickReplayer
Replays recorded ticks:
- Configurable speed multiplier
- Sequence range and instrument filters
- Calls `on_tick` callback with correct inter-tick delays
- Drives the mock engine as if receiving live ticks

```python
replayer = TickReplayer()
replayer.load_entries(recorded_data)
replayer.configure(ReplayConfig(speed_multiplier=10.0))
await replayer.play()  # Replays at 10x speed
```

## Configuration

```yaml
# config/mock.yaml
mock:
  default_capital: 1000000.0       # Starting capital (₹)
  slippage_pct: 0.05               # Slippage percentage
  brokerage_per_order: 20.0        # Brokerage per order (₹)
  speed_multiplier: 1.0            # Default time speed
  auto_fill_market_orders: true    # Instant market order fills
  realistic_fills: true            # Apply slippage
  market_hours_only: true          # Only accept orders during market hours
```

## Frontend Mock Testing Page

The Mock Testing page provides:
- **Create Session Form**: Set capital, start/end dates
- **Session Overview**: Capital, P&L, current time, progress
- **Time Controls**: All time manipulation buttons (market open/close, next day, speed, pause/resume, date jump, reset)
- **Positions Table**: Current mock positions with P&L
- **Orders Table**: Mock order history
