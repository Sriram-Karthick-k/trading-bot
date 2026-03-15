# Risk Management

The platform enforces pre-trade risk checks on every order before it reaches the broker. The `RiskManager` runs 9 sequential checks and blocks orders that violate any limit.

## Risk Check Pipeline

Every order passes through these checks in order:

| # | Check | Blocks When |
|---|-------|-------------|
| 1 | **Kill Switch** | Kill switch is active |
| 2 | **Max Order Value** | `price × quantity > max_order_value` |
| 3 | **Max Position Value** | Total position value would exceed limit |
| 4 | **Daily Loss Limit** | Cumulative daily loss exceeds `max_daily_loss` |
| 5 | **Open Orders Limit** | Number of open orders ≥ `max_open_orders` |
| 6 | **Open Positions Limit** | Number of positions ≥ `max_open_positions` |
| 7 | **Max Quantity** | Order quantity > `max_quantity_per_order` |
| 8 | **Exchange Allowed** | Exchange not in `allowed_exchanges` list |
| 9 | **Trading Hours** | Current time outside `trading_start_hour`–`trading_end_hour` |
| 10 | **Order Rate Limit** | Orders in last 60s ≥ `max_orders_per_minute` |

If any check fails, the order is **rejected** with a descriptive reason.

## Risk Limits

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_order_value` | ₹5,00,000 | Maximum value per individual order |
| `max_position_value` | ₹10,00,000 | Maximum total position value |
| `max_loss_per_trade` | ₹10,000 | Maximum loss per individual trade |
| `max_daily_loss` | ₹50,000 | Maximum cumulative daily loss |
| `max_open_orders` | 20 | Maximum concurrent open orders |
| `max_open_positions` | 10 | Maximum concurrent positions |
| `max_quantity_per_order` | 5,000 | Maximum quantity in a single order |
| `max_orders_per_minute` | 30 | Order placement rate limit |
| `allowed_exchanges` | NSE, BSE, NFO, MCX, CDS, BFO | Exchanges allowed for trading |
| `trading_start_hour` | 09:15 | Market open time (IST) |
| `trading_end_hour` | 15:30 | Market close time (IST) |

## Kill Switch

The kill switch is an **emergency stop** that immediately blocks all new orders:

### Activation
```
POST /api/config/risk/kill-switch/activate
```
- Blocks all `place_order()` calls
- Existing positions are NOT closed (manual exit required)
- Persists until explicitly deactivated

### Deactivation
```
POST /api/config/risk/kill-switch/deactivate
```
- Re-enables order placement
- Does NOT automatically resume strategies

### When to Use
- Unexpected market volatility
- System malfunction detected
- Daily loss approaching limit
- Manual intervention needed

## Daily Loss Tracking

The `RiskManager` tracks cumulative daily loss:

```python
# Called after every trade closes
risk_manager.record_trade_pnl(pnl_amount)

# Check status
status = risk_manager.get_status()
# {
#   "daily_loss": 12500.0,
#   "daily_loss_limit": 50000.0,
#   "daily_loss_pct": 25.0,
#   ...
# }
```

When daily loss reaches the limit, all further orders are automatically blocked until the next trading day.

## Order Rate Limiting

The system tracks timestamps of recent orders and blocks new orders if the rate exceeds `max_orders_per_minute`:

```
Order timestamps: [10:00:01, 10:00:15, 10:00:30, 10:00:45]
Current time: 10:01:00
Orders in last 60s: 4
Limit: 30/minute → PASSED
```

## Risk Status API

### Get Current Status
```
GET /api/config/risk/status
```

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

### Update Limits
```
PUT /api/config/risk/limits
```

```json
{
  "max_order_value": 600000,
  "max_daily_loss": 75000,
  "max_open_positions": 15
}
```

## Frontend Risk Panel

The dashboard displays:
- **Daily Loss Bar**: Visual progress bar showing daily loss utilization (green → amber → red)
- **Order Rate**: Current orders per minute
- **Kill Switch**: Toggle with confirmation
- **Risk Status**: Real-time metrics refreshed every 2 seconds

## Configuration

Risk limits can be set at three levels:

1. **Runtime** via Settings page or API (`PUT /api/config/risk/limits`)
2. **YAML** in `config/risk.yaml`
3. **Environment** via `TRADE_MAX_DAILY_LOSS`, `TRADE_KILL_SWITCH`, etc.
