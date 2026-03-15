"""
Mock trading simulation engine.

Simulates order matching, fill execution, position tracking,
and P&L calculation — all in-memory, no real trades.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.clock import VirtualClock
from app.providers.types import (
    Exchange,
    Holding,
    LTPQuote,
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
    TickData,
    Trade,
    TransactionType,
    Variety,
    Validity,
)

logger = logging.getLogger(__name__)


@dataclass
class MockFill:
    """Internal record of a simulated trade fill."""
    order_id: str
    trade_id: str
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    transaction_type: TransactionType
    product: ProductType
    quantity: int
    price: float
    slippage: float
    brokerage: float
    timestamp: datetime


@dataclass
class PositionState:
    """Internal position state tracked by the engine."""
    tradingsymbol: str
    exchange: Exchange
    instrument_token: int
    product: ProductType
    quantity: int = 0
    average_price: float = 0.0
    buy_quantity: int = 0
    buy_value: float = 0.0
    sell_quantity: int = 0
    sell_value: float = 0.0
    realized_pnl: float = 0.0


class MockEngine:
    """
    Core simulation engine for mock/paper trading.

    Handles:
    - Order placement, modification, cancellation
    - Fill simulation with configurable slippage
    - Position tracking and P&L calculation
    - Virtual margin/capital management
    """

    def __init__(
        self,
        capital: float = 100000.0,
        slippage_pct: float = 0.05,
        brokerage_per_order: float = 20.0,
        clock: VirtualClock | None = None,
    ):
        self._clock = clock or VirtualClock()
        self.initial_capital = capital
        self.available_capital = capital
        self.slippage_pct = slippage_pct
        self.brokerage_per_order = brokerage_per_order

        # State
        self._orders: dict[str, Order] = {}
        self._order_history: dict[str, list[OrderUpdate]] = {}
        self._trades: list[Trade] = []
        self._fills: list[MockFill] = []
        self._positions: dict[str, PositionState] = {}  # key: "exchange:symbol:product"
        self._holdings: list[Holding] = []
        self._ltp: dict[int, float] = {}  # instrument_token -> last traded price
        self._instrument_map: dict[str, int] = {}  # "exchange:symbol" -> token
        self._historical: dict[str, list] = {}  # "{token}:{interval}" -> candles

        # Counters
        self._order_counter = 0
        self._trade_counter = 0
        self.total_brokerage = 0.0

    @property
    def realized_pnl(self) -> float:
        return sum(p.realized_pnl for p in self._positions.values())

    @property
    def unrealized_pnl(self) -> float:
        total = 0.0
        for p in self._positions.values():
            if p.quantity != 0:
                ltp = self._ltp.get(p.instrument_token, p.average_price)
                if p.quantity > 0:
                    total += (ltp - p.average_price) * p.quantity
                else:
                    total += (p.average_price - ltp) * abs(p.quantity)
        return total

    # ─── Price Management ─────────────────────────────────────────────────

    def set_ltp(self, instrument_token: int, price: float) -> None:
        """Set the last traded price for an instrument."""
        self._ltp[instrument_token] = price

    def get_current_price(self, instrument_token: int) -> float:
        """Get the current LTP for an instrument."""
        return self._ltp.get(instrument_token, 0.0)

    def update_prices_from_ticks(self, ticks: list[TickData]) -> None:
        """Update LTPs from incoming tick data and check pending orders."""
        for tick in ticks:
            self._ltp[tick.instrument_token] = tick.last_price
        self._check_pending_orders()

    def register_instrument(self, exchange: str, symbol: str, token: int) -> None:
        """Register an instrument mapping."""
        self._instrument_map[f"{exchange}:{symbol}"] = token

    # ─── Order Management ─────────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> str:
        """Place a simulated order. Returns order_id."""
        self._order_counter += 1
        order_id = f"MOCK{self._order_counter:012d}"
        now = self._clock.now()

        token = self._instrument_map.get(f"{request.exchange.value}:{request.tradingsymbol}", 0)

        order = Order(
            order_id=order_id,
            tradingsymbol=request.tradingsymbol,
            exchange=request.exchange,
            transaction_type=request.transaction_type,
            order_type=request.order_type,
            product=request.product,
            variety=request.variety,
            status=OrderStatus.OPEN,
            quantity=request.quantity,
            price=request.price,
            trigger_price=request.trigger_price,
            average_price=0.0,
            filled_quantity=0,
            pending_quantity=request.quantity,
            cancelled_quantity=0,
            disclosed_quantity=request.disclosed_quantity,
            validity=request.validity,
            instrument_token=token,
            tag=request.tag,
            order_timestamp=now,
        )

        self._orders[order_id] = order
        self._order_history[order_id] = [
            OrderUpdate(order_id=order_id, status=OrderStatus.OPEN, timestamp=now),
        ]

        # MARKET and SL-M orders fill immediately at current LTP ± slippage
        if request.order_type == OrderType.MARKET:
            self._execute_market_fill(order)
        elif request.order_type == OrderType.STOPLOSS_MARKET:
            # Trigger pending until price reaches trigger
            order.status = OrderStatus.TRIGGER_PENDING
            self._order_history[order_id].append(
                OrderUpdate(order_id=order_id, status=OrderStatus.TRIGGER_PENDING, timestamp=now)
            )
        elif request.order_type in (OrderType.LIMIT, OrderType.STOPLOSS):
            # Check if limit can be filled immediately
            self._try_limit_fill(order)

        logger.info("Mock order placed: %s %s %s qty=%d @ %s",
                     order_id, request.transaction_type.value,
                     request.tradingsymbol, request.quantity,
                     request.order_type.value)
        return order_id

    def modify_order(self, order_id: str, request: OrderRequest) -> None:
        """Modify a pending order."""
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order.status not in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING):
            raise ValueError(f"Order {order_id} cannot be modified (status: {order.status.value})")

        order.quantity = request.quantity
        order.price = request.price
        order.trigger_price = request.trigger_price
        order.order_type = request.order_type
        order.pending_quantity = request.quantity - order.filled_quantity
        order.modified = True

        now = self._clock.now()
        self._order_history[order_id].append(
            OrderUpdate(order_id=order_id, status=OrderStatus.MODIFIED, timestamp=now)
        )

        # Re-check fill conditions
        if order.order_type == OrderType.MARKET:
            self._execute_market_fill(order)
        else:
            self._try_limit_fill(order)

    def cancel_order(self, order_id: str) -> None:
        """Cancel a pending order."""
        order = self._orders.get(order_id)
        if not order:
            raise ValueError(f"Order {order_id} not found")
        if order.status not in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING):
            raise ValueError(f"Order {order_id} cannot be cancelled (status: {order.status.value})")

        order.status = OrderStatus.CANCELLED
        order.cancelled_quantity = order.pending_quantity
        order.pending_quantity = 0

        now = self._clock.now()
        self._order_history[order_id].append(
            OrderUpdate(order_id=order_id, status=OrderStatus.CANCELLED, timestamp=now)
        )

    # ─── Fill Simulation ──────────────────────────────────────────────────

    def _execute_market_fill(self, order: Order) -> None:
        """Fill a market order immediately at LTP ± slippage."""
        ltp = self.get_current_price(order.instrument_token)
        if ltp <= 0:
            # No price available; use order price or reject
            if order.price is not None and order.price > 0:
                ltp = order.price
            else:
                order.status = OrderStatus.REJECTED
                order.status_message = "No market price available"
                self._order_history[order.order_id].append(
                    OrderUpdate(order_id=order.order_id, status=OrderStatus.REJECTED,
                                timestamp=self._clock.now())
                )
                return

        # Apply slippage
        slippage_amount = ltp * (self.slippage_pct / 100)
        if order.transaction_type == TransactionType.BUY:
            fill_price = ltp + slippage_amount
        else:
            fill_price = ltp - slippage_amount
        fill_price = round(fill_price, 2)

        self._fill_order(order, fill_price, slippage_amount)

    def _try_limit_fill(self, order: Order) -> None:
        """Check if a limit order can be filled at current price."""
        ltp = self.get_current_price(order.instrument_token)
        if ltp <= 0:
            return  # Stay pending

        can_fill = False
        if order.order_type == OrderType.LIMIT:
            if order.transaction_type == TransactionType.BUY and ltp <= order.price:
                can_fill = True
            elif order.transaction_type == TransactionType.SELL and ltp >= order.price:
                can_fill = True
        elif order.order_type == OrderType.STOPLOSS:
            if order.trigger_price > 0:
                if order.transaction_type == TransactionType.BUY and ltp >= order.trigger_price:
                    can_fill = True
                elif order.transaction_type == TransactionType.SELL and ltp <= order.trigger_price:
                    can_fill = True

        if can_fill:
            fill_price = order.price if order.price > 0 else ltp
            self._fill_order(order, fill_price, 0.0)

    def _check_pending_orders(self) -> None:
        """Check all pending orders against current prices."""
        for order in self._orders.values():
            if order.status == OrderStatus.OPEN:
                self._try_limit_fill(order)
            elif order.status == OrderStatus.TRIGGER_PENDING:
                ltp = self.get_current_price(order.instrument_token)
                if ltp <= 0:
                    continue
                triggered = False
                if order.transaction_type == TransactionType.BUY and ltp >= order.trigger_price:
                    triggered = True
                elif order.transaction_type == TransactionType.SELL and ltp <= order.trigger_price:
                    triggered = True
                if triggered:
                    if order.order_type == OrderType.STOPLOSS_MARKET:
                        self._execute_market_fill(order)
                    else:
                        order.status = OrderStatus.OPEN
                        self._try_limit_fill(order)

    def _fill_order(self, order: Order, fill_price: float, slippage: float) -> None:
        """Execute a fill for an order."""
        fill_qty = order.pending_quantity
        now = self._clock.now()

        # Check margin
        required = fill_price * fill_qty + self.brokerage_per_order
        if order.transaction_type == TransactionType.BUY and required > self.available_capital:
            order.status = OrderStatus.REJECTED
            order.status_message = (
                f"Insufficient funds. Required: {required:.2f}, "
                f"Available: {self.available_capital:.2f}"
            )
            self._order_history[order.order_id].append(
                OrderUpdate(order_id=order.order_id, status=OrderStatus.REJECTED, timestamp=now)
            )
            return

        # Create trade
        self._trade_counter += 1
        trade_id = f"MOCKT{self._trade_counter:012d}"

        trade = Trade(
            trade_id=trade_id,
            order_id=order.order_id,
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            instrument_token=order.instrument_token,
            transaction_type=order.transaction_type,
            product=order.product,
            average_price=fill_price,
            quantity=fill_qty,
            fill_timestamp=now,
            order_timestamp=order.order_timestamp,
            exchange_timestamp=now,
        )
        self._trades.append(trade)

        fill = MockFill(
            order_id=order.order_id,
            trade_id=trade_id,
            tradingsymbol=order.tradingsymbol,
            exchange=order.exchange,
            instrument_token=order.instrument_token,
            transaction_type=order.transaction_type,
            product=order.product,
            quantity=fill_qty,
            price=fill_price,
            slippage=slippage,
            brokerage=self.brokerage_per_order,
            timestamp=now,
        )
        self._fills.append(fill)

        # Update order
        order.filled_quantity = fill_qty
        order.pending_quantity = 0
        order.average_price = fill_price
        order.status = OrderStatus.COMPLETE
        order.exchange_timestamp = now
        self._order_history[order.order_id].append(
            OrderUpdate(order_id=order.order_id, status=OrderStatus.COMPLETE,
                        timestamp=now, filled_quantity=fill_qty, average_price=fill_price)
        )

        # Update capital and positions
        self.total_brokerage += self.brokerage_per_order
        self.available_capital -= self.brokerage_per_order
        self._update_position(order, fill_price, fill_qty)

    def _update_position(self, order: Order, fill_price: float, fill_qty: int) -> None:
        """Update position state after a fill."""
        pos_key = f"{order.exchange.value}:{order.tradingsymbol}:{order.product.value}"

        if pos_key not in self._positions:
            self._positions[pos_key] = PositionState(
                tradingsymbol=order.tradingsymbol,
                exchange=order.exchange,
                instrument_token=order.instrument_token,
                product=order.product,
            )

        pos = self._positions[pos_key]

        if order.transaction_type == TransactionType.BUY:
            cost = fill_price * fill_qty
            self.available_capital -= cost
            pos.buy_quantity += fill_qty
            pos.buy_value += cost

            if pos.quantity >= 0:
                # Adding to long
                total_qty = pos.quantity + fill_qty
                if total_qty > 0:
                    pos.average_price = (pos.average_price * pos.quantity + cost) / total_qty
                pos.quantity = total_qty
            else:
                # Covering short
                pnl = (pos.average_price - fill_price) * min(fill_qty, abs(pos.quantity))
                pos.realized_pnl += pnl
                self.available_capital += pnl
                pos.quantity += fill_qty
                if pos.quantity > 0:
                    pos.average_price = fill_price
        else:  # SELL
            proceeds = fill_price * fill_qty
            self.available_capital += proceeds
            pos.sell_quantity += fill_qty
            pos.sell_value += proceeds

            if pos.quantity <= 0:
                # Adding to short
                total_qty = abs(pos.quantity) + fill_qty
                if total_qty > 0:
                    pos.average_price = (pos.average_price * abs(pos.quantity) + proceeds) / total_qty
                pos.quantity -= fill_qty
            else:
                # Closing long
                pnl = (fill_price - pos.average_price) * min(fill_qty, pos.quantity)
                pos.realized_pnl += pnl
                pos.quantity -= fill_qty
                if pos.quantity < 0:
                    pos.average_price = fill_price

    # ─── Query Methods ────────────────────────────────────────────────────

    def get_orders(self) -> list[Order]:
        return list(self._orders.values())

    def get_order_history(self, order_id: str) -> list[OrderUpdate]:
        return self._order_history.get(order_id, [])

    def get_trades(self) -> list[Trade]:
        return list(self._trades)

    def get_positions(self) -> PositionsData:
        positions = []
        for pos in self._positions.values():
            if pos.quantity == 0 and pos.buy_quantity == 0 and pos.sell_quantity == 0:
                continue
            ltp = self._ltp.get(pos.instrument_token, pos.average_price)
            pnl = pos.realized_pnl
            if pos.quantity != 0:
                if pos.quantity > 0:
                    pnl += (ltp - pos.average_price) * pos.quantity
                else:
                    pnl += (pos.average_price - ltp) * abs(pos.quantity)

            positions.append(Position(
                tradingsymbol=pos.tradingsymbol,
                exchange=pos.exchange,
                instrument_token=pos.instrument_token,
                product=pos.product,
                quantity=pos.quantity,
                overnight_quantity=0,
                multiplier=1,
                average_price=pos.average_price,
                close_price=0,
                last_price=ltp,
                value=pos.buy_value - pos.sell_value,
                pnl=pnl,
                m2m=pnl,
                unrealised=pnl - pos.realized_pnl,
                realised=pos.realized_pnl,
                buy_quantity=pos.buy_quantity,
                buy_price=pos.buy_value / pos.buy_quantity if pos.buy_quantity else 0,
                buy_value=pos.buy_value,
                sell_quantity=pos.sell_quantity,
                sell_price=pos.sell_value / pos.sell_quantity if pos.sell_quantity else 0,
                sell_value=pos.sell_value,
                day_buy_quantity=pos.buy_quantity,
                day_buy_price=pos.buy_value / pos.buy_quantity if pos.buy_quantity else 0,
                day_buy_value=pos.buy_value,
                day_sell_quantity=pos.sell_quantity,
                day_sell_price=pos.sell_value / pos.sell_quantity if pos.sell_quantity else 0,
                day_sell_value=pos.sell_value,
            ))
        return PositionsData(net=positions, day=positions)

    def get_holdings(self) -> list[Holding]:
        return list(self._holdings)

    def get_quotes(self, instruments: list[str]) -> dict[str, Quote]:
        result = {}
        for inst in instruments:
            token = self._instrument_map.get(inst, 0)
            ltp = self._ltp.get(token, 0)
            result[inst] = Quote(
                instrument_token=token,
                timestamp=self._clock.now(),
                last_trade_time=self._clock.now(),
                last_price=ltp,
                last_quantity=0,
                buy_quantity=0,
                sell_quantity=0,
                volume=0,
                average_price=ltp,
                oi=0,
                oi_day_high=0,
                oi_day_low=0,
                net_change=0,
                lower_circuit_limit=0,
                upper_circuit_limit=0,
                ohlc_open=ltp,
                ohlc_high=ltp,
                ohlc_low=ltp,
                ohlc_close=ltp,
            )
        return result

    def get_ltp(self, instruments: list[str]) -> dict[str, LTPQuote]:
        result = {}
        for inst in instruments:
            token = self._instrument_map.get(inst, 0)
            ltp = self._ltp.get(token, 0)
            result[inst] = LTPQuote(instrument_token=token, last_price=ltp)
        return result

    def get_ohlc(self, instruments: list[str]) -> dict[str, OHLCQuote]:
        result = {}
        for inst in instruments:
            token = self._instrument_map.get(inst, 0)
            ltp = self._ltp.get(token, 0)
            result[inst] = OHLCQuote(
                instrument_token=token, last_price=ltp,
                ohlc_open=ltp, ohlc_high=ltp, ohlc_low=ltp, ohlc_close=ltp,
            )
        return result

    # ─── Reset ────────────────────────────────────────────────────────────

    def reset(self, capital: float | None = None) -> None:
        """Reset all state for a fresh session."""
        if capital is not None:
            self.initial_capital = capital
        self.available_capital = self.initial_capital
        self._orders.clear()
        self._order_history.clear()
        self._trades.clear()
        self._fills.clear()
        self._positions.clear()
        self._holdings.clear()
        self._ltp.clear()
        self._historical.clear()
        self._order_counter = 0
        self._trade_counter = 0
        self.total_brokerage = 0.0

    # ─── Sample Data ──────────────────────────────────────────────────────

    # Approximate real prices for popular Indian stocks (for paper trading)
    SAMPLE_INSTRUMENTS: list[dict] = [
        {"symbol": "RELIANCE", "token": 738561, "price": 1430.0, "name": "Reliance Industries"},
        {"symbol": "TCS", "token": 2953217, "price": 3860.0, "name": "Tata Consultancy Services"},
        {"symbol": "INFY", "token": 408065, "price": 1550.0, "name": "Infosys"},
        {"symbol": "HDFCBANK", "token": 341249, "price": 1870.0, "name": "HDFC Bank"},
        {"symbol": "ICICIBANK", "token": 1270529, "price": 1340.0, "name": "ICICI Bank"},
        {"symbol": "SBIN", "token": 779521, "price": 830.0, "name": "State Bank of India"},
        {"symbol": "BHARTIARTL", "token": 2714625, "price": 1720.0, "name": "Bharti Airtel"},
        {"symbol": "ITC", "token": 424961, "price": 460.0, "name": "ITC"},
        {"symbol": "KOTAKBANK", "token": 492033, "price": 1930.0, "name": "Kotak Mahindra Bank"},
        {"symbol": "LT", "token": 2939649, "price": 3550.0, "name": "Larsen & Toubro"},
        {"symbol": "WIPRO", "token": 969473, "price": 455.0, "name": "Wipro"},
        {"symbol": "HINDUNILVR", "token": 356865, "price": 2350.0, "name": "Hindustan Unilever"},
        {"symbol": "AXISBANK", "token": 1510401, "price": 1210.0, "name": "Axis Bank"},
        {"symbol": "TATAMOTORS", "token": 884737, "price": 730.0, "name": "Tata Motors"},
        {"symbol": "SUNPHARMA", "token": 857857, "price": 1800.0, "name": "Sun Pharmaceutical"},
        {"symbol": "BAJFINANCE", "token": 81153, "price": 8900.0, "name": "Bajaj Finance"},
        {"symbol": "MARUTI", "token": 2756609, "price": 12500.0, "name": "Maruti Suzuki"},
        {"symbol": "TITAN", "token": 897537, "price": 3200.0, "name": "Titan Company"},
        {"symbol": "ASIANPAINT", "token": 60417, "price": 2850.0, "name": "Asian Paints"},
        {"symbol": "HCLTECH", "token": 1850625, "price": 1680.0, "name": "HCL Technologies"},
    ]

    def load_sample_data(self) -> dict:
        """Load sample NSE instrument data with approximate prices for paper trading."""
        loaded = 0
        for item in self.SAMPLE_INSTRUMENTS:
            self.register_instrument("NSE", item["symbol"], item["token"])
            self.set_ltp(item["token"], item["price"])
            loaded += 1

        # Generate synthetic historical candles for each instrument
        self._generate_synthetic_history()

        return {
            "instruments_loaded": loaded,
            "symbols": [i["symbol"] for i in self.SAMPLE_INSTRUMENTS],
        }

    def _generate_synthetic_history(self) -> None:
        """Generate realistic synthetic OHLCV candles for all sample instruments."""
        import hashlib
        import math
        from datetime import timedelta
        from app.providers.types import Candle, CandleInterval

        now = self._clock.now().replace(hour=15, minute=30, second=0, microsecond=0)

        for item in self.SAMPLE_INSTRUMENTS:
            token = item["token"]
            base_price = item["price"]

            # Generate 365 daily candles
            daily_candles: list[Candle] = []
            price = base_price * 0.85  # start ~15% below current
            for day_offset in range(365, 0, -1):
                dt = now - timedelta(days=day_offset)
                if dt.weekday() >= 5:  # skip weekends
                    continue
                # Deterministic "random" using hash so data is stable
                seed = int(hashlib.md5(f"{token}:{day_offset}".encode()).hexdigest()[:8], 16)
                trend = 0.15 / 252  # ~15% annual drift
                volatility = 0.02  # 2% daily vol
                noise = ((seed % 1000) / 500.0 - 1.0) * volatility
                change = 1 + trend + noise
                price = round(price * change, 2)
                day_vol = (seed % 5000 + 1000) * 100
                high_pct = 1 + ((seed >> 4) % 20) / 1000
                low_pct = 1 - ((seed >> 8) % 20) / 1000
                o = round(price * (1 + ((seed >> 12) % 10 - 5) / 1000), 2)
                h = round(max(o, price) * high_pct, 2)
                low = round(min(o, price) * low_pct, 2)
                daily_candles.append(Candle(
                    timestamp=dt.replace(hour=9, minute=15),
                    open=o, high=h, low=low, close=price,
                    volume=day_vol, oi=0,
                ))

            self._historical[f"{token}:{CandleInterval.DAY.value}"] = daily_candles

            # Generate intraday candles for last 5 trading days
            for interval, minutes, iv_key in [
                (CandleInterval.MINUTE, 1, "minute"),
                (CandleInterval.MINUTE_5, 5, "5minute"),
                (CandleInterval.MINUTE_15, 15, "15minute"),
                (CandleInterval.MINUTE_60, 60, "60minute"),
            ]:
                intraday: list[Candle] = []
                for day_offset in range(5, 0, -1):
                    dt = now - timedelta(days=day_offset)
                    if dt.weekday() >= 5:
                        continue
                    p = base_price * (1 + ((day_offset * 7 + token) % 50 - 25) / 1000)
                    market_start = dt.replace(hour=9, minute=15, second=0)
                    market_end = dt.replace(hour=15, minute=30, second=0)
                    t = market_start
                    while t < market_end:
                        seed = int(hashlib.md5(f"{token}:{t.isoformat()}".encode()).hexdigest()[:8], 16)
                        noise = ((seed % 1000) / 500.0 - 1.0) * 0.003
                        p = round(p * (1 + noise), 2)
                        high_pct = 1 + ((seed >> 4) % 10) / 1000
                        low_pct = 1 - ((seed >> 8) % 10) / 1000
                        o = round(p * (1 + ((seed >> 12) % 6 - 3) / 1000), 2)
                        h = round(max(o, p) * high_pct, 2)
                        low = round(min(o, p) * low_pct, 2)
                        vol = (seed % 2000 + 100) * (60 // max(minutes, 1))
                        intraday.append(Candle(
                            timestamp=t, open=o, high=h, low=low, close=p,
                            volume=vol, oi=0,
                        ))
                        t += timedelta(minutes=minutes)

                self._historical[f"{token}:{iv_key}"] = intraday

    def get_sample_as_instruments(self) -> list:
        """Return sample data as Instrument dataclass instances."""
        from app.providers.types import Exchange, Instrument
        result = []
        for item in self.SAMPLE_INSTRUMENTS:
            result.append(Instrument(
                instrument_token=item["token"],
                exchange_token=item["token"] // 256,
                tradingsymbol=item["symbol"],
                name=item["name"],
                exchange=Exchange.NSE,
                segment="NSE",
                instrument_type="EQ",
                lot_size=1,
                tick_size=0.05,
                last_price=self._ltp.get(item["token"], item["price"]),
            ))
        return result

    def get_sample_instruments(self) -> list[dict]:
        """Return sample instruments with current LTP from the engine."""
        result = []
        for item in self.SAMPLE_INSTRUMENTS:
            ltp = self._ltp.get(item["token"], item["price"])
            result.append({
                "symbol": item["symbol"],
                "token": item["token"],
                "name": item["name"],
                "ltp": ltp,
                "exchange": "NSE",
            })
        return result
