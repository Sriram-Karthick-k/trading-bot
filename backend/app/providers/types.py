"""
Provider-agnostic types for the trading platform.

All broker providers map their responses to these common types.
This ensures strategy code, risk management, and UI never depend
on any specific broker's data format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Callable, Protocol


# ─── Enums ────────────────────────────────────────────────────────────────────


class Exchange(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    CDS = "CDS"
    BCD = "BCD"
    MCX = "MCX"
    BFO = "BFO"
    MF = "MF"


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOPLOSS = "SL"
    STOPLOSS_MARKET = "SL-M"


class ProductType(str, Enum):
    CNC = "CNC"       # Cash & Carry (delivery)
    NRML = "NRML"     # Normal (F&O overnight)
    MIS = "MIS"       # Margin Intraday Squareoff
    MTF = "MTF"       # Margin Trading Facility


class Variety(str, Enum):
    REGULAR = "regular"
    AMO = "amo"            # After Market Order
    CO = "co"              # Cover Order
    ICEBERG = "iceberg"
    AUCTION = "auction"


class Validity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"    # Immediate or Cancel
    TTL = "TTL"    # Time to Live (minutes)


class OrderStatus(str, Enum):
    PUT_ORDER_REQ_RECEIVED = "PUT ORDER REQ RECEIVED"
    VALIDATION_PENDING = "VALIDATION PENDING"
    OPEN_PENDING = "OPEN PENDING"
    OPEN = "OPEN"
    TRIGGER_PENDING = "TRIGGER PENDING"
    MODIFY_VALIDATION_PENDING = "MODIFY VALIDATION PENDING"
    MODIFY_PENDING = "MODIFY PENDING"
    MODIFIED = "MODIFIED"
    CANCEL_PENDING = "CANCEL PENDING"
    CANCELLED = "CANCELLED"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    AMO_REQ_RECEIVED = "AMO REQ RECEIVED"


class TickMode(str, Enum):
    LTP = "ltp"
    QUOTE = "quote"
    FULL = "full"


class InstrumentType(str, Enum):
    EQ = "EQ"
    FUT = "FUT"
    CE = "CE"
    PE = "PE"


class Segment(str, Enum):
    NSE = "NSE"
    BSE = "BSE"
    NFO_FUT = "NFO-FUT"
    NFO_OPT = "NFO-OPT"
    CDS_FUT = "CDS-FUT"
    CDS_OPT = "CDS-OPT"
    BCD_FUT = "BCD-FUT"
    BCD_OPT = "BCD-OPT"
    BFO_FUT = "BFO-FUT"
    BFO_OPT = "BFO-OPT"
    MCX_FUT = "MCX-FUT"
    MCX_OPT = "MCX-OPT"
    MF = "MF"
    INDICES = "INDICES"


# ─── Data Classes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Credentials:
    """Provider-specific credentials."""
    api_key: str
    api_secret: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Session:
    """Authenticated session from a provider."""
    user_id: str
    access_token: str
    provider_name: str
    login_time: datetime
    user_name: str = ""
    email: str = ""
    broker: str = ""
    exchanges: list[Exchange] = field(default_factory=list)
    products: list[ProductType] = field(default_factory=list)
    order_types: list[OrderType] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderRequest:
    """Request to place an order."""
    tradingsymbol: str
    exchange: Exchange
    transaction_type: TransactionType
    order_type: OrderType
    quantity: int
    product: ProductType
    variety: Variety = Variety.REGULAR
    price: float = 0.0
    trigger_price: float = 0.0
    disclosed_quantity: int = 0
    validity: Validity = Validity.DAY
    validity_ttl: int = 0
    tag: str = ""


@dataclass(frozen=True)
class OrderResponse:
    """Response after placing/modifying/cancelling an order."""
    order_id: str
    status: str = "success"
    message: str = ""


@dataclass
class Order:
    """Full order details from the order book."""
    order_id: str
    tradingsymbol: str
    exchange: Exchange
    transaction_type: TransactionType
    order_type: OrderType
    product: ProductType
    variety: Variety
    status: OrderStatus
    quantity: int
    price: float
    trigger_price: float
    average_price: float
    filled_quantity: int
    pending_quantity: int
    cancelled_quantity: int
    disclosed_quantity: int
    validity: Validity
    instrument_token: int = 0
    exchange_order_id: str | None = None
    parent_order_id: str | None = None
    placed_by: str = ""
    tag: str | None = None
    status_message: str | None = None
    order_timestamp: datetime | None = None
    exchange_timestamp: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    modified: bool = False
    guid: str = ""


@dataclass
class OrderUpdate:
    """A single state change in order history."""
    order_id: str
    status: OrderStatus
    timestamp: datetime | None = None
    filled_quantity: int = 0
    pending_quantity: int = 0
    price: float = 0.0
    trigger_price: float = 0.0
    average_price: float = 0.0


@dataclass
class Trade:
    """A single executed trade (fill)."""
    trade_id: str
    order_id: str
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    transaction_type: TransactionType
    product: ProductType
    average_price: float
    quantity: int
    fill_timestamp: datetime | None = None
    order_timestamp: datetime | None = None
    exchange_timestamp: datetime | None = None
    exchange_order_id: str | None = None


@dataclass
class Position:
    """Active position (net or day)."""
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    product: ProductType
    quantity: int
    overnight_quantity: int
    multiplier: int
    average_price: float
    close_price: float
    last_price: float
    value: float
    pnl: float
    m2m: float
    unrealised: float
    realised: float
    buy_quantity: int
    buy_price: float
    buy_value: float
    sell_quantity: int
    sell_price: float
    sell_value: float
    day_buy_quantity: int = 0
    day_buy_price: float = 0.0
    day_buy_value: float = 0.0
    day_sell_quantity: int = 0
    day_sell_price: float = 0.0
    day_sell_value: float = 0.0


@dataclass(frozen=True)
class PositionsData:
    """Container for net and day positions."""
    net: list[Position] = field(default_factory=list)
    day: list[Position] = field(default_factory=list)


@dataclass
class Holding:
    """Long-term equity holding."""
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    isin: str
    quantity: int
    t1_quantity: int
    average_price: float
    last_price: float
    close_price: float
    pnl: float
    day_change: float
    day_change_percentage: float
    product: ProductType = ProductType.CNC
    collateral_quantity: int = 0
    collateral_type: str | None = None
    used_quantity: int = 0
    realised_quantity: int = 0
    authorised_quantity: int = 0
    opening_quantity: int = 0
    discrepancy: bool = False


@dataclass
class MarketDepthEntry:
    """Single level of market depth (bid/ask)."""
    price: float
    quantity: int
    orders: int


@dataclass
class Quote:
    """Full market quote for an instrument."""
    instrument_token: int
    timestamp: datetime | None
    last_trade_time: datetime | None
    last_price: float
    last_quantity: int
    buy_quantity: int
    sell_quantity: int
    volume: int
    average_price: float
    oi: float  # Open Interest
    oi_day_high: float
    oi_day_low: float
    net_change: float
    lower_circuit_limit: float
    upper_circuit_limit: float
    ohlc_open: float
    ohlc_high: float
    ohlc_low: float
    ohlc_close: float
    depth_buy: list[MarketDepthEntry] = field(default_factory=list)
    depth_sell: list[MarketDepthEntry] = field(default_factory=list)


@dataclass(frozen=True)
class LTPQuote:
    """Last traded price quote."""
    instrument_token: int
    last_price: float


@dataclass(frozen=True)
class OHLCQuote:
    """OHLC + LTP quote."""
    instrument_token: int
    last_price: float
    ohlc_open: float
    ohlc_high: float
    ohlc_low: float
    ohlc_close: float


@dataclass(frozen=True)
class Candle:
    """Single OHLCV candle bar."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int = 0


class CandleInterval(str, Enum):
    MINUTE = "minute"
    MINUTE_3 = "3minute"
    MINUTE_5 = "5minute"
    MINUTE_10 = "10minute"
    MINUTE_15 = "15minute"
    MINUTE_30 = "30minute"
    MINUTE_60 = "60minute"
    DAY = "day"


@dataclass
class Instrument:
    """Tradable instrument master data."""
    instrument_token: int
    exchange_token: int
    tradingsymbol: str
    name: str
    exchange: Exchange
    segment: str
    instrument_type: str
    lot_size: int
    tick_size: float
    last_price: float = 0.0
    expiry: date | None = None
    strike: float = 0.0


@dataclass
class TickData:
    """Real-time tick data from WebSocket."""
    instrument_token: int
    timestamp: datetime | None = None
    last_price: float = 0.0
    last_quantity: int = 0
    average_price: float = 0.0
    volume: int = 0
    buy_quantity: int = 0
    sell_quantity: int = 0
    ohlc_open: float = 0.0
    ohlc_high: float = 0.0
    ohlc_low: float = 0.0
    ohlc_close: float = 0.0
    change: float = 0.0
    oi: int = 0
    oi_day_high: int = 0
    oi_day_low: int = 0
    exchange_timestamp: datetime | None = None
    depth_buy: list[MarketDepthEntry] = field(default_factory=list)
    depth_sell: list[MarketDepthEntry] = field(default_factory=list)
    mode: TickMode = TickMode.LTP


@dataclass
class MarginSegment:
    """Margin data for a single segment (equity/commodity)."""
    enabled: bool
    net: float
    available_cash: float
    opening_balance: float
    live_balance: float
    intraday_payin: float
    adhoc_margin: float
    collateral: float
    utilised_debits: float
    utilised_exposure: float
    utilised_span: float
    utilised_option_premium: float
    utilised_holding_sales: float
    utilised_turnover: float
    utilised_m2m_realised: float
    utilised_m2m_unrealised: float
    utilised_payout: float
    utilised_liquid_collateral: float
    utilised_stock_collateral: float
    utilised_delivery: float


@dataclass(frozen=True)
class MarginsData:
    """Funds and margins across segments."""
    equity: MarginSegment | None = None
    commodity: MarginSegment | None = None


@dataclass(frozen=True)
class ProviderInfo:
    """Metadata about a broker provider."""
    name: str
    display_name: str
    supported_exchanges: list[Exchange]
    supported_products: list[ProductType]
    supported_order_types: list[OrderType]
    supported_varieties: list[Variety]
    features: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthStatus:
    """Health check result for a provider."""
    healthy: bool
    provider_name: str
    latency_ms: float = 0.0
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ─── Ticker Protocol ─────────────────────────────────────────────────────────


class TickerConnection(Protocol):
    """Protocol for WebSocket ticker connections."""

    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def is_connected(self) -> bool: ...
    def subscribe(self, instrument_tokens: list[int], mode: TickMode = TickMode.QUOTE) -> None: ...
    def unsubscribe(self, instrument_tokens: list[int]) -> None: ...
    def set_on_tick(self, callback: Callable[[list[TickData]], None]) -> None: ...
    def set_on_order_update(self, callback: Callable[[dict], None]) -> None: ...
    def set_on_connect(self, callback: Callable[[], None]) -> None: ...
    def set_on_disconnect(self, callback: Callable[[int, str | None], None]) -> None: ...
    def set_on_error(self, callback: Callable[[Exception], None]) -> None: ...
