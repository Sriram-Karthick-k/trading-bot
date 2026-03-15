# Strategy Framework

The platform includes a strategy framework for automated trading. Strategies receive market data, generate trading signals, and the platform handles risk checking and order execution.

## Architecture

```
Market Data
    │
    ▼
Strategy.on_tick(tick) / on_candle(candle)
    │
    ▼
_emit_signal(StrategySignal)
    │
    ▼
OrderManager.process_signals()
    │
    ▼
RiskManager.check_order()
    │  passed
    ▼
Provider.place_order()
```

Strategies **never** place orders directly. They emit signals that pass through risk management before execution.

## Strategy Lifecycle

```
IDLE ──start()──▶ RUNNING ──pause()──▶ PAUSED
  ▲                  │                    │
  │                  │ stop()          resume()
  │                  ▼                    │
  └────────────── STOPPED ◀───────────────┘
                     │
              (error) ▼
                   ERROR
```

| State | Description |
|-------|-------------|
| `IDLE` | Created but not started |
| `RUNNING` | Actively receiving data and generating signals |
| `PAUSED` | Temporarily suspended, retains state |
| `STOPPED` | Gracefully terminated |
| `ERROR` | Stopped due to error |

## Abstract Strategy Class

```python
class Strategy(ABC):
    # Required implementations
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def get_params_schema(self) -> list[ParamDef]: ...

    @abstractmethod
    def get_instruments(self) -> list[int]: ...

    @abstractmethod
    def on_tick(self, tick: TickData) -> None: ...

    @abstractmethod
    def on_candle(self, candle: Candle) -> None: ...

    # Optional overrides
    def initialize(self) -> None: ...      # Called on start
    def on_order_update(self, order) -> None: ...  # Fill notifications
    def shutdown(self) -> None: ...        # Called on stop

    # Signal emission
    def _emit_signal(self, signal: StrategySignal) -> None: ...

    # Signal consumption (by OrderManager)
    def consume_signals(self) -> list[StrategySignal]: ...
```

## Parameter Schema

Each strategy defines its configurable parameters via `ParamDef`:

```python
@dataclass
class ParamDef:
    name: str                    # Parameter key
    param_type: str              # "int", "float", "str", "bool"
    default: Any                 # Default value
    min_value: float | None      # Minimum (for numeric)
    max_value: float | None      # Maximum (for numeric)
    enum_values: list | None     # Allowed values (for str)
    description: str             # Human-readable description
```

Parameters are validated against the schema before being applied. Out-of-range or invalid enum values are rejected.

## Strategy Signal

```python
@dataclass
class StrategySignal:
    instrument_token: int        # Which instrument
    trading_symbol: str          # Symbol name
    action: str                  # "BUY", "SELL", or "EXIT"
    order_request: OrderRequest | None  # Optional detailed order spec
    reason: str                  # Why the signal was generated
    confidence: float            # 0.0 to 1.0 confidence score
```

## Strategy Metrics

Every strategy automatically tracks:

| Metric | Description |
|--------|-------------|
| `total_signals` | Total signals emitted |
| `total_trades` | Orders that were filled |
| `winning_trades` | Trades with positive P&L |
| `losing_trades` | Trades with negative P&L |
| `total_pnl` | Cumulative P&L |
| `max_drawdown` | Maximum peak-to-trough decline |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/strategies/` | GET | List all strategies |
| `/api/strategies/types` | GET | Available strategy types + schemas |
| `/api/strategies/{id}` | GET | Get state snapshot |
| `/api/strategies/{id}/start` | POST | Start strategy |
| `/api/strategies/{id}/stop` | POST | Stop strategy |
| `/api/strategies/{id}/pause` | POST | Pause strategy |
| `/api/strategies/{id}/resume` | POST | Resume strategy |
| `/api/strategies/{id}/params` | PUT | Update parameters |
| `/api/strategies/{id}` | DELETE | Remove strategy |

## Implementing a Strategy

1. Create a new file in `backend/app/strategies/`
2. Subclass `Strategy`
3. Implement required abstract methods
4. Register in strategy discovery

```python
from app.strategies.base import Strategy, ParamDef, StrategySignal

class MyStrategy(Strategy):
    def name(self) -> str:
        return "My Strategy"

    def description(self) -> str:
        return "A custom trading strategy"

    def get_params_schema(self) -> list[ParamDef]:
        return [
            ParamDef("lookback", "int", 20, 5, 200, None, "Lookback period"),
            ParamDef("threshold", "float", 2.0, 0.1, 10.0, None, "Signal threshold"),
        ]

    def get_instruments(self) -> list[int]:
        return [256265]  # RELIANCE instrument token

    def on_tick(self, tick):
        # Analyze tick data
        if self._should_buy(tick):
            self._emit_signal(StrategySignal(
                instrument_token=tick.instrument_token,
                trading_symbol="RELIANCE",
                action="BUY",
                reason="Breakout detected",
                confidence=0.85,
            ))

    def on_candle(self, candle):
        pass  # Handle candle data
```
