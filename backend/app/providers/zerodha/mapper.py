"""
Mapper for converting Kite Connect API responses to provider-agnostic types.

Every field from the Kite API is explicitly mapped here. This is the ONLY
place that knows about Kite-specific data formats.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.providers.types import (
    Candle,
    Exchange,
    Holding,
    Instrument,
    LTPQuote,
    MarginSegment,
    MarginsData,
    MarketDepthEntry,
    OHLCQuote,
    Order,
    OrderRequest,
    OrderStatus,
    OrderType,
    OrderUpdate,
    Position,
    PositionsData,
    ProductType,
    Quote,
    Session,
    TickData,
    TickMode,
    Trade,
    TransactionType,
    Validity,
    Variety,
)

# ─── Kite → Common enum mappings ──────────────────────────────────────────────

_ORDER_TYPE_MAP: dict[str, OrderType] = {
    "MARKET": OrderType.MARKET,
    "LIMIT": OrderType.LIMIT,
    "SL": OrderType.STOPLOSS,
    "SL-M": OrderType.STOPLOSS_MARKET,
}
_ORDER_TYPE_REVERSE: dict[OrderType, str] = {v: k for k, v in _ORDER_TYPE_MAP.items()}

_PRODUCT_MAP: dict[str, ProductType] = {
    "CNC": ProductType.CNC,
    "NRML": ProductType.NRML,
    "MIS": ProductType.MIS,
    "MTF": ProductType.MTF,
}
_PRODUCT_REVERSE: dict[ProductType, str] = {v: k for k, v in _PRODUCT_MAP.items()}

_EXCHANGE_MAP: dict[str, Exchange] = {e.value: e for e in Exchange}

_VARIETY_MAP: dict[str, Variety] = {
    "regular": Variety.REGULAR,
    "amo": Variety.AMO,
    "co": Variety.CO,
    "iceberg": Variety.ICEBERG,
    "auction": Variety.AUCTION,
}
_VARIETY_REVERSE: dict[Variety, str] = {v: k for k, v in _VARIETY_MAP.items()}

_VALIDITY_MAP: dict[str, Validity] = {
    "DAY": Validity.DAY,
    "IOC": Validity.IOC,
    "TTL": Validity.TTL,
}

_STATUS_MAP: dict[str, OrderStatus] = {s.value: s for s in OrderStatus}


def _parse_status(raw: str) -> OrderStatus:
    """Parse order status string, with fallback."""
    return _STATUS_MAP.get(raw, OrderStatus.OPEN)


def _parse_datetime(val: Any) -> datetime | None:
    """Parse datetime from Kite response (string or datetime)."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z", "%H:%M:%S"):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return None


def _parse_date(val: Any) -> date | None:
    """Parse date from Kite response."""
    if val is None:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, str):
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


class ZerodhaMapper:
    """Maps Kite Connect API responses to common provider types."""

    # ─── Session ──────────────────────────────────────────────────────────

    def to_session(self, data: dict, provider_name: str) -> Session:
        return Session(
            user_id=data.get("user_id", ""),
            access_token=data.get("access_token", ""),
            provider_name=provider_name,
            login_time=_parse_datetime(data.get("login_time")) or datetime.now(),
            user_name=data.get("user_name", ""),
            email=data.get("email", ""),
            broker=data.get("broker", ""),
            exchanges=[_EXCHANGE_MAP[e] for e in data.get("exchanges", []) if e in _EXCHANGE_MAP],
            products=[_PRODUCT_MAP[p] for p in data.get("products", []) if p in _PRODUCT_MAP],
            order_types=[_ORDER_TYPE_MAP[o] for o in data.get("order_types", []) if o in _ORDER_TYPE_MAP],
            extra={
                "public_token": data.get("public_token", ""),
                "refresh_token": data.get("refresh_token", ""),
                "avatar_url": data.get("avatar_url", ""),
                "meta": data.get("meta", {}),
            },
        )

    # ─── Orders ───────────────────────────────────────────────────────────

    def from_order_request(self, order: OrderRequest) -> dict:
        """Convert OrderRequest to Kite API parameters."""
        params: dict[str, Any] = {
            "variety": _VARIETY_REVERSE.get(order.variety, "regular"),
            "tradingsymbol": order.tradingsymbol,
            "exchange": order.exchange.value,
            "transaction_type": order.transaction_type.value,
            "order_type": _ORDER_TYPE_REVERSE.get(order.order_type, "MARKET"),
            "quantity": order.quantity,
            "product": _PRODUCT_REVERSE.get(order.product, "MIS"),
            "validity": order.validity.value,
        }
        if order.price:
            params["price"] = order.price
        if order.trigger_price:
            params["trigger_price"] = order.trigger_price
        if order.disclosed_quantity:
            params["disclosed_quantity"] = order.disclosed_quantity
        if order.validity_ttl:
            params["validity_ttl"] = order.validity_ttl
        if order.tag:
            params["tag"] = order.tag
        return params

    def to_order(self, data: dict) -> Order:
        return Order(
            order_id=str(data.get("order_id", "")),
            tradingsymbol=data.get("tradingsymbol", ""),
            exchange=_EXCHANGE_MAP.get(data.get("exchange", ""), Exchange.NSE),
            transaction_type=TransactionType(data.get("transaction_type", "BUY")),
            order_type=_ORDER_TYPE_MAP.get(data.get("order_type", ""), OrderType.MARKET),
            product=_PRODUCT_MAP.get(data.get("product", ""), ProductType.MIS),
            variety=_VARIETY_MAP.get(data.get("variety", ""), Variety.REGULAR),
            status=_parse_status(data.get("status", "OPEN")),
            quantity=int(data.get("quantity", 0)),
            price=float(data.get("price", 0)),
            trigger_price=float(data.get("trigger_price", 0)),
            average_price=float(data.get("average_price", 0)),
            filled_quantity=int(data.get("filled_quantity", 0)),
            pending_quantity=int(data.get("pending_quantity", 0)),
            cancelled_quantity=int(data.get("cancelled_quantity", 0)),
            disclosed_quantity=int(data.get("disclosed_quantity", 0)),
            validity=_VALIDITY_MAP.get(data.get("validity", "DAY"), Validity.DAY),
            instrument_token=int(data.get("instrument_token", 0)),
            exchange_order_id=data.get("exchange_order_id"),
            parent_order_id=data.get("parent_order_id"),
            placed_by=data.get("placed_by", ""),
            tag=data.get("tag"),
            status_message=data.get("status_message"),
            order_timestamp=_parse_datetime(data.get("order_timestamp")),
            exchange_timestamp=_parse_datetime(data.get("exchange_timestamp")),
            meta=data.get("meta", {}),
            modified=data.get("modified", False),
            guid=data.get("guid", ""),
        )

    def to_order_update(self, data: dict) -> OrderUpdate:
        return OrderUpdate(
            order_id=str(data.get("order_id", "")),
            status=_parse_status(data.get("status", "OPEN")),
            timestamp=_parse_datetime(data.get("order_timestamp")),
            filled_quantity=int(data.get("filled_quantity", 0)),
            pending_quantity=int(data.get("pending_quantity", 0)),
            price=float(data.get("price", 0)),
            trigger_price=float(data.get("trigger_price", 0)),
            average_price=float(data.get("average_price", 0)),
        )

    def to_trade(self, data: dict) -> Trade:
        return Trade(
            trade_id=str(data.get("trade_id", "")),
            order_id=str(data.get("order_id", "")),
            tradingsymbol=data.get("tradingsymbol", ""),
            exchange=_EXCHANGE_MAP.get(data.get("exchange", ""), Exchange.NSE),
            instrument_token=int(data.get("instrument_token", 0)),
            transaction_type=TransactionType(data.get("transaction_type", "BUY")),
            product=_PRODUCT_MAP.get(data.get("product", ""), ProductType.MIS),
            average_price=float(data.get("average_price", 0)),
            quantity=int(data.get("quantity", 0)),
            fill_timestamp=_parse_datetime(data.get("fill_timestamp")),
            order_timestamp=_parse_datetime(data.get("order_timestamp")),
            exchange_timestamp=_parse_datetime(data.get("exchange_timestamp")),
            exchange_order_id=data.get("exchange_order_id"),
        )

    # ─── Portfolio ────────────────────────────────────────────────────────

    def to_position(self, data: dict) -> Position:
        return Position(
            tradingsymbol=data.get("tradingsymbol", ""),
            exchange=_EXCHANGE_MAP.get(data.get("exchange", ""), Exchange.NSE),
            instrument_token=int(data.get("instrument_token", 0)),
            product=_PRODUCT_MAP.get(data.get("product", ""), ProductType.MIS),
            quantity=int(data.get("quantity", 0)),
            overnight_quantity=int(data.get("overnight_quantity", 0)),
            multiplier=int(data.get("multiplier", 1)),
            average_price=float(data.get("average_price", 0)),
            close_price=float(data.get("close_price", 0)),
            last_price=float(data.get("last_price", 0)),
            value=float(data.get("value", 0)),
            pnl=float(data.get("pnl", 0)),
            m2m=float(data.get("m2m", 0)),
            unrealised=float(data.get("unrealised", 0)),
            realised=float(data.get("realised", 0)),
            buy_quantity=int(data.get("buy_quantity", 0)),
            buy_price=float(data.get("buy_price", 0)),
            buy_value=float(data.get("buy_value", 0)),
            sell_quantity=int(data.get("sell_quantity", 0)),
            sell_price=float(data.get("sell_price", 0)),
            sell_value=float(data.get("sell_value", 0)),
            day_buy_quantity=int(data.get("day_buy_quantity", 0)),
            day_buy_price=float(data.get("day_buy_price", 0)),
            day_buy_value=float(data.get("day_buy_value", 0)),
            day_sell_quantity=int(data.get("day_sell_quantity", 0)),
            day_sell_price=float(data.get("day_sell_price", 0)),
            day_sell_value=float(data.get("day_sell_value", 0)),
        )

    def to_positions_data(self, data: dict) -> PositionsData:
        return PositionsData(
            net=[self.to_position(p) for p in data.get("net", [])],
            day=[self.to_position(p) for p in data.get("day", [])],
        )

    def to_holding(self, data: dict) -> Holding:
        return Holding(
            tradingsymbol=data.get("tradingsymbol", ""),
            exchange=_EXCHANGE_MAP.get(data.get("exchange", ""), Exchange.NSE),
            instrument_token=int(data.get("instrument_token", 0)),
            isin=data.get("isin", ""),
            quantity=int(data.get("quantity", 0)),
            t1_quantity=int(data.get("t1_quantity", 0)),
            average_price=float(data.get("average_price", 0)),
            last_price=float(data.get("last_price", 0)),
            close_price=float(data.get("close_price", 0)),
            pnl=float(data.get("pnl", 0)),
            day_change=float(data.get("day_change", 0)),
            day_change_percentage=float(data.get("day_change_percentage", 0)),
            product=_PRODUCT_MAP.get(data.get("product", "CNC"), ProductType.CNC),
            collateral_quantity=int(data.get("collateral_quantity", 0)),
            collateral_type=data.get("collateral_type"),
            used_quantity=int(data.get("used_quantity", 0)),
            realised_quantity=int(data.get("realised_quantity", 0)),
            authorised_quantity=int(data.get("authorised_quantity", 0)),
            opening_quantity=int(data.get("opening_quantity", 0)),
            discrepancy=data.get("discrepancy", False),
        )

    # ─── Market Data ──────────────────────────────────────────────────────

    def to_quote(self, data: dict) -> Quote:
        ohlc = data.get("ohlc", {})
        depth = data.get("depth", {})
        return Quote(
            instrument_token=int(data.get("instrument_token", 0)),
            timestamp=_parse_datetime(data.get("timestamp")),
            last_trade_time=_parse_datetime(data.get("last_trade_time")),
            last_price=float(data.get("last_price", 0)),
            last_quantity=int(data.get("last_quantity", 0)),
            buy_quantity=int(data.get("buy_quantity", 0)),
            sell_quantity=int(data.get("sell_quantity", 0)),
            volume=int(data.get("volume", 0)),
            average_price=float(data.get("average_price", 0)),
            oi=float(data.get("oi", 0)),
            oi_day_high=float(data.get("oi_day_high", 0)),
            oi_day_low=float(data.get("oi_day_low", 0)),
            net_change=float(data.get("net_change", 0)),
            lower_circuit_limit=float(data.get("lower_circuit_limit", 0)),
            upper_circuit_limit=float(data.get("upper_circuit_limit", 0)),
            ohlc_open=float(ohlc.get("open", 0)),
            ohlc_high=float(ohlc.get("high", 0)),
            ohlc_low=float(ohlc.get("low", 0)),
            ohlc_close=float(ohlc.get("close", 0)),
            depth_buy=[
                MarketDepthEntry(
                    price=float(d.get("price", 0)),
                    quantity=int(d.get("quantity", 0)),
                    orders=int(d.get("orders", 0)),
                )
                for d in depth.get("buy", [])
            ],
            depth_sell=[
                MarketDepthEntry(
                    price=float(d.get("price", 0)),
                    quantity=int(d.get("quantity", 0)),
                    orders=int(d.get("orders", 0)),
                )
                for d in depth.get("sell", [])
            ],
        )

    def to_ltp_quote(self, data: dict) -> LTPQuote:
        return LTPQuote(
            instrument_token=int(data.get("instrument_token", 0)),
            last_price=float(data.get("last_price", 0)),
        )

    def to_ohlc_quote(self, data: dict) -> OHLCQuote:
        ohlc = data.get("ohlc", {})
        return OHLCQuote(
            instrument_token=int(data.get("instrument_token", 0)),
            last_price=float(data.get("last_price", 0)),
            ohlc_open=float(ohlc.get("open", 0)),
            ohlc_high=float(ohlc.get("high", 0)),
            ohlc_low=float(ohlc.get("low", 0)),
            ohlc_close=float(ohlc.get("close", 0)),
        )

    def to_candle(self, data: dict | list) -> Candle:
        if isinstance(data, list):
            # [timestamp, open, high, low, close, volume, oi?]
            return Candle(
                timestamp=data[0] if isinstance(data[0], datetime) else _parse_datetime(data[0]) or datetime.now(),
                open=float(data[1]),
                high=float(data[2]),
                low=float(data[3]),
                close=float(data[4]),
                volume=int(data[5]),
                oi=int(data[6]) if len(data) > 6 else 0,
            )
        return Candle(
            timestamp=_parse_datetime(data.get("date")) or datetime.now(),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            volume=int(data.get("volume", 0)),
            oi=int(data.get("oi", 0)),
        )

    def to_instrument(self, data: dict) -> Instrument:
        return Instrument(
            instrument_token=int(data.get("instrument_token", 0)),
            exchange_token=int(data.get("exchange_token", 0)),
            tradingsymbol=data.get("tradingsymbol", ""),
            name=data.get("name", ""),
            exchange=_EXCHANGE_MAP.get(data.get("exchange", ""), Exchange.NSE),
            segment=data.get("segment", ""),
            instrument_type=data.get("instrument_type", ""),
            lot_size=int(data.get("lot_size", 1)),
            tick_size=float(data.get("tick_size", 0.05)),
            last_price=float(data.get("last_price", 0)),
            expiry=_parse_date(data.get("expiry")),
            strike=float(data.get("strike", 0)),
        )

    # ─── Margins ──────────────────────────────────────────────────────────

    def _to_margin_segment(self, data: dict) -> MarginSegment:
        available = data.get("available", {})
        utilised = data.get("utilised", {})
        return MarginSegment(
            enabled=data.get("enabled", False),
            net=float(data.get("net", 0)),
            available_cash=float(available.get("cash", 0)),
            opening_balance=float(available.get("opening_balance", 0)),
            live_balance=float(available.get("live_balance", 0)),
            intraday_payin=float(available.get("intraday_payin", 0)),
            adhoc_margin=float(available.get("adhoc_margin", 0)),
            collateral=float(available.get("collateral", 0)),
            utilised_debits=float(utilised.get("debits", 0)),
            utilised_exposure=float(utilised.get("exposure", 0)),
            utilised_span=float(utilised.get("span", 0)),
            utilised_option_premium=float(utilised.get("option_premium", 0)),
            utilised_holding_sales=float(utilised.get("holding_sales", 0)),
            utilised_turnover=float(utilised.get("turnover", 0)),
            utilised_m2m_realised=float(utilised.get("m2m_realised", 0)),
            utilised_m2m_unrealised=float(utilised.get("m2m_unrealised", 0)),
            utilised_payout=float(utilised.get("payout", 0)),
            utilised_liquid_collateral=float(utilised.get("liquid_collateral", 0)),
            utilised_stock_collateral=float(utilised.get("stock_collateral", 0)),
            utilised_delivery=float(utilised.get("delivery", 0)),
        )

    def to_margins_data(self, data: dict) -> MarginsData:
        return MarginsData(
            equity=self._to_margin_segment(data["equity"]) if "equity" in data else None,
            commodity=self._to_margin_segment(data["commodity"]) if "commodity" in data else None,
        )

    # ─── Tick Data ────────────────────────────────────────────────────────

    def to_tick_data(self, data: dict) -> TickData:
        ohlc = data.get("ohlc", {})
        depth = data.get("depth", {})
        return TickData(
            instrument_token=int(data.get("instrument_token", 0)),
            timestamp=_parse_datetime(data.get("timestamp")),
            last_price=float(data.get("last_price", 0)),
            last_quantity=int(data.get("last_quantity", 0)),
            average_price=float(data.get("average_traded_price", 0)),
            volume=int(data.get("volume_traded", data.get("volume", 0))),
            buy_quantity=int(data.get("total_buy_quantity", data.get("buy_quantity", 0))),
            sell_quantity=int(data.get("total_sell_quantity", data.get("sell_quantity", 0))),
            ohlc_open=float(ohlc.get("open", 0)),
            ohlc_high=float(ohlc.get("high", 0)),
            ohlc_low=float(ohlc.get("low", 0)),
            ohlc_close=float(ohlc.get("close", 0)),
            change=float(data.get("change", 0)),
            oi=int(data.get("oi", 0)),
            oi_day_high=int(data.get("oi_day_high", 0)),
            oi_day_low=int(data.get("oi_day_low", 0)),
            exchange_timestamp=_parse_datetime(data.get("exchange_timestamp")),
            depth_buy=[
                MarketDepthEntry(
                    price=float(d.get("price", 0)),
                    quantity=int(d.get("quantity", 0)),
                    orders=int(d.get("orders", 0)),
                )
                for d in depth.get("buy", [])
            ],
            depth_sell=[
                MarketDepthEntry(
                    price=float(d.get("price", 0)),
                    quantity=int(d.get("quantity", 0)),
                    orders=int(d.get("orders", 0)),
                )
                for d in depth.get("sell", [])
            ],
            mode=TickMode(data.get("mode", "ltp")),
        )
