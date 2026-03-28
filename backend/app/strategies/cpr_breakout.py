"""
CPR (Central Pivot Range) Breakout Strategy.

Scans major NIFTY sector indices for narrow CPR days and generates
breakout signals using first-candle confirmation on 5-minute data.

CPR Levels:
    Pivot = (High + Low + Close) / 3
    TC (Top Central Pivot) = (Pivot - BC) + Pivot  =  2 * Pivot - BC
    BC (Bottom Central Pivot) = (High + Low) / 2

Narrow CPR: when width_pct < threshold (default 0.3%), price is likely
to break out strongly in one direction.

Entry:
    LONG  — first 5-min candle closes above TC
    SHORT — first 5-min candle closes below BC

Exit:
    SL at opposite CPR boundary, target at risk_reward * SL distance.
    Auto-close at end of day (intraday only, MIS product).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.providers.types import (
    Candle,
    Exchange,
    OrderRequest,
    OrderType,
    ProductType,
    TickData,
    TransactionType,
    Variety,
    Validity,
)
from app.services.decision_log import decision_log
from app.strategies.base import ParamDef, ParamType, Strategy, StrategySignal

logger = logging.getLogger(__name__)


# ── NIFTY Sector Index Tokens ───────────────────────────────────────────────

NIFTY_INDEX_TOKENS: dict[str, int] = {
    "NIFTY 50": 256265,
    "NIFTY BANK": 260105,
    "NIFTY IT": 259849,
    "NIFTY FIN SERVICE": 257801,
    "NIFTY PHARMA": 262409,
    "NIFTY AUTO": 263433,
    "NIFTY METAL": 263689,
    "NIFTY ENERGY": 261641,
    "NIFTY FMCG": 261897,
    "NIFTY REALTY": 261129,
    "NIFTY INFRA": 261385,
    "NIFTY PSU BANK": 262921,
    "NIFTY MEDIA": 263945,
    "NIFTY MIDCAP 50": 260873,
    "NIFTY MIDCAP 100": 256777,
    "NIFTY MID SELECT": 288009,
}


# ── CPR Calculation ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CPRLevels:
    """Central Pivot Range levels computed from previous day OHLC."""

    pivot: float
    tc: float      # Top Central Pivot
    bc: float      # Bottom Central Pivot
    width: float   # Absolute width (tc - bc)
    width_pct: float  # Width as percentage of pivot

    @property
    def is_narrow(self) -> bool:
        """Check if CPR is narrow (< 0.3% by default)."""
        return self.width_pct < 0.3


def calculate_cpr(high: float, low: float, close: float) -> CPRLevels:
    """
    Calculate CPR levels from previous day's High, Low, Close.

    Formula:
        Pivot = (H + L + C) / 3
        BC = (H + L) / 2
        TC = 2 * Pivot - BC  =  (H + L + 2*C) / 3 - (H + L) / 6
            simplified: TC = 2 * Pivot - BC

    TC is always >= BC by construction when close >= (H+L)/2,
    but we normalize so tc >= bc always.
    """
    pivot = (high + low + close) / 3.0
    bc = (high + low) / 2.0
    tc = 2.0 * pivot - bc  # = (2*(H+L+C)/3) - (H+L)/2

    # Ensure tc >= bc (swap if close is far from midrange)
    if tc < bc:
        tc, bc = bc, tc

    width = tc - bc
    width_pct = (width / pivot) * 100.0 if pivot > 0 else 0.0

    return CPRLevels(
        pivot=round(pivot, 2),
        tc=round(tc, 2),
        bc=round(bc, 2),
        width=round(width, 2),
        width_pct=round(width_pct, 4),
    )


# ── Strategy ────────────────────────────────────────────────────────────────


class CPRBreakoutStrategy(Strategy):
    """
    CPR Breakout — scans for narrow CPR and trades the breakout direction.

    Uses 5-minute intraday candles. On each new trading day:
    1. Computes CPR from the previous day's daily OHLC.
    2. If CPR width_pct < narrow_threshold, watches for a breakout.
    3. Entry: first 5-min candle that closes above TC (LONG) or below BC (SHORT).
    4. SL: opposite CPR boundary. Target: risk_reward_ratio * SL distance.
    5. Auto-exits at end of day.

    Parameters:
        narrow_threshold: CPR width % below which breakout is expected (default: 0.3)
        risk_reward_ratio: Target distance as multiple of SL distance (default: 2.0)
        instrument_token: Token of the instrument to trade
        trading_symbol: Symbol name
        exchange: Exchange (default: NSE)
        quantity: Order quantity per signal (default: 1)
    """

    def __init__(self, strategy_id: str, params: dict[str, Any] | None = None):
        super().__init__(strategy_id, params)

        # Previous day OHLC accumulation
        self._current_day: str | None = None   # "YYYY-MM-DD"
        self._day_high: float = 0.0
        self._day_low: float = float("inf")
        self._day_close: float = 0.0
        self._day_open: float = 0.0

        # CPR for the current trading day (calculated from previous day)
        self._cpr: CPRLevels | None = None
        self._prev_day_ohlc: dict[str, float] | None = None

        # Intraday position tracking
        self._position: str | None = None   # "LONG", "SHORT", or None
        self._entry_price: float = 0.0
        self._stop_loss: float = 0.0
        self._target: float = 0.0
        self._traded_today: bool = False     # Only one trade per day

        # Trailing stop loss tracking
        self._trailing_peak: float = 0.0  # High watermark (LONG) or low watermark (SHORT)

        # Order confirmation guard — prevents SL checks before entry order is placed
        self._order_confirmed: bool = False

        # History of daily OHLC for building CPR
        self._first_candle_seen: bool = False

    @classmethod
    def name(cls) -> str:
        return "cpr_breakout"

    @classmethod
    def description(cls) -> str:
        return (
            "CPR (Central Pivot Range) Breakout. Identifies narrow CPR days on "
            "NIFTY sector indices and trades the breakout direction using "
            "first-candle confirmation on 5-minute data."
        )

    @classmethod
    def get_params_schema(cls) -> list[ParamDef]:
        return [
            ParamDef(
                name="narrow_threshold",
                param_type=ParamType.FLOAT,
                default=0.3,
                label="Narrow CPR Threshold %",
                description="CPR width percentage below which a breakout is expected",
                min_value=0.01,
                max_value=2.0,
            ),
            ParamDef(
                name="risk_reward_ratio",
                param_type=ParamType.FLOAT,
                default=2.0,
                label="Risk/Reward Ratio",
                description="Target as multiple of stop-loss distance",
                min_value=0.5,
                max_value=10.0,
            ),
            ParamDef(
                name="instrument_token",
                param_type=ParamType.INT,
                default=0,
                label="Instrument Token",
                description="Numeric token of the instrument to trade",
            ),
            ParamDef(
                name="trading_symbol",
                param_type=ParamType.STRING,
                default="",
                label="Trading Symbol",
                description="e.g. NIFTY 50, NIFTY BANK",
            ),
            ParamDef(
                name="exchange",
                param_type=ParamType.STRING,
                default="NSE",
                label="Exchange",
                description="Exchange (NSE, BSE, NFO, etc.)",
            ),
            ParamDef(
                name="quantity",
                param_type=ParamType.INT,
                default=1,
                label="Quantity",
                description="Lots/shares per signal",
                min_value=1,
                max_value=10000,
            ),
            ParamDef(
                name="trail_activation_pct",
                param_type=ParamType.FLOAT,
                default=0.3,
                label="Trail Activation %",
                description="Profit percentage to activate trailing SL (0 = always trail)",
                min_value=0.0,
                max_value=5.0,
            ),
            ParamDef(
                name="trail_distance_pct",
                param_type=ParamType.FLOAT,
                default=0.2,
                label="Trail Distance %",
                description="Trailing SL distance from peak price as percentage",
                min_value=0.05,
                max_value=3.0,
            ),
            ParamDef(
                name="min_sl_distance_pct",
                param_type=ParamType.FLOAT,
                default=0.1,
                label="Min SL Distance %",
                description="Minimum stop-loss distance as percentage of entry price (prevents sub-tick SL)",
                min_value=0.01,
                max_value=2.0,
            ),
        ]

    def get_instruments(self) -> list[int]:
        token = self.get_param("instrument_token", 0)
        return [token] if token else []

    async def on_order_update(self, order: Any) -> None:
        """
        Called when an order placed by this strategy is confirmed filled.
        Sets _order_confirmed so tick-level SL/target checks can begin.
        """
        from app.providers.types import OrderStatus
        status = getattr(order, "status", None)
        if status == OrderStatus.COMPLETE:
            self._order_confirmed = True
            decision_log.log("strategy", "info", "Order confirmed — SL/target checks active", {
                "symbol": self.get_param("trading_symbol"),
                "order_id": getattr(order, "order_id", "?"),
                "position": self._position,
            })

    async def on_tick(self, tick: TickData) -> None:
        """
        Check SL/target/trailing-SL on every tick for instant exits.

        Called for every raw tick from KiteTicker, so exits happen within
        seconds of price breach rather than waiting up to 5 minutes for the
        next completed candle.

        Trailing SL logic:
        - LONG: if price moves above entry by `trail_activation_pct`%, start
          trailing. Trail SL to `price - trail_distance` whenever price makes
          a new high. Never move SL downward.
        - SHORT: mirror logic for downward moves.
        """
        if self._position is None:
            return

        # Guard: don't check SL/target until entry order is confirmed filled
        if not self._order_confirmed:
            return

        if tick.instrument_token != self.get_param("instrument_token"):
            return

        price = tick.last_price
        if price <= 0:
            return

        ts = tick.timestamp or datetime.now()

        # ── Trailing stop loss ──────────────────────────────────────
        trail_pct = self.get_param("trail_activation_pct", 0.3)  # Activate after 0.3% move in profit
        trail_distance_pct = self.get_param("trail_distance_pct", 0.2)  # Trail by 0.2% from peak
        min_sl_pct = self.get_param("min_sl_distance_pct", 0.1)  # Minimum SL distance

        if self._position == "LONG":
            # Track high water mark
            if price > self._trailing_peak:
                self._trailing_peak = price

            # Activate trailing once price moved trail_pct% above entry
            profit_pct = ((price - self._entry_price) / self._entry_price) * 100.0
            if profit_pct >= trail_pct and self._trailing_peak > 0:
                trail_sl = self._trailing_peak * (1.0 - trail_distance_pct / 100.0)
                # Fix #4: Only replace SL if trailing SL locks in profit (above entry)
                # Fix #6: Enforce minimum SL distance from current price
                min_sl_distance = price * (min_sl_pct / 100.0)
                if (
                    trail_sl > self._stop_loss
                    and trail_sl > self._entry_price  # Must lock in profit
                    and (price - trail_sl) >= min_sl_distance  # Min distance
                ):
                    old_sl = self._stop_loss
                    self._stop_loss = round(trail_sl, 2)
                    decision_log.log("strategy", "info", "Trailing SL updated (LONG)", {
                        "symbol": self.get_param("trading_symbol"),
                        "old_sl": old_sl, "new_sl": self._stop_loss,
                        "peak": self._trailing_peak, "price": price,
                    })
                    logger.debug(
                        "Trailing SL updated LONG %s: %.2f → %.2f (peak=%.2f)",
                        self.get_param("trading_symbol"), old_sl, self._stop_loss,
                        self._trailing_peak,
                    )

            # ── Check SL / target ───────────────────────────────────
            if price <= self._stop_loss:
                self._close_position_at_price(
                    price, ts, f"Tick SL hit at {price:.2f} (SL={self._stop_loss:.2f})"
                )
                return
            if price >= self._target:
                self._close_position_at_price(
                    price, ts, f"Tick target hit at {price:.2f} (target={self._target:.2f})"
                )
                return

        elif self._position == "SHORT":
            # Track low water mark
            if price < self._trailing_peak:
                self._trailing_peak = price

            # Activate trailing once price moved trail_pct% below entry
            profit_pct = ((self._entry_price - price) / self._entry_price) * 100.0
            if profit_pct >= trail_pct and self._trailing_peak > 0:
                trail_sl = self._trailing_peak * (1.0 + trail_distance_pct / 100.0)
                # Fix #4: Only replace SL if trailing SL locks in profit (below entry)
                # Fix #6: Enforce minimum SL distance from current price
                min_sl_distance = price * (min_sl_pct / 100.0)
                if (
                    trail_sl < self._stop_loss
                    and trail_sl < self._entry_price  # Must lock in profit
                    and (trail_sl - price) >= min_sl_distance  # Min distance
                ):
                    old_sl = self._stop_loss
                    self._stop_loss = round(trail_sl, 2)
                    decision_log.log("strategy", "info", "Trailing SL updated (SHORT)", {
                        "symbol": self.get_param("trading_symbol"),
                        "old_sl": old_sl, "new_sl": self._stop_loss,
                        "trough": self._trailing_peak, "price": price,
                    })
                    logger.debug(
                        "Trailing SL updated SHORT %s: %.2f → %.2f (trough=%.2f)",
                        self.get_param("trading_symbol"), old_sl, self._stop_loss,
                        self._trailing_peak,
                    )

            # ── Check SL / target ───────────────────────────────────
            if price >= self._stop_loss:
                self._close_position_at_price(
                    price, ts, f"Tick SL hit at {price:.2f} (SL={self._stop_loss:.2f})"
                )
                return
            if price <= self._target:
                self._close_position_at_price(
                    price, ts, f"Tick target hit at {price:.2f} (target={self._target:.2f})"
                )
                return

    async def on_candle(self, instrument_token: int, candle: Candle) -> None:
        """
        Process each 5-minute candle:
        1. Detect day transitions to compute CPR from previous day.
        2. Check for breakout entry if CPR is narrow.
        3. Check for SL/target exit on open positions.
        4. Auto-close at end of day.
        """
        if instrument_token != self.get_param("instrument_token"):
            return

        candle_day = candle.timestamp.strftime("%Y-%m-%d")

        # ── Day transition ──────────────────────────────────────────
        if self._current_day is None:
            # Very first candle — initialize day tracking
            self._current_day = candle_day
            self._day_open = candle.open
            self._day_high = candle.high
            self._day_low = candle.low
            self._day_close = candle.close
            self._first_candle_seen = True
            return

        if candle_day != self._current_day:
            # New day — close any open position from yesterday
            if self._position is not None:
                self._close_position(candle, "End of day auto-close")

            # Save previous day's OHLC
            self._prev_day_ohlc = {
                "open": self._day_open,
                "high": self._day_high,
                "low": self._day_low,
                "close": self._day_close,
            }

            # Calculate CPR from previous day
            self._cpr = calculate_cpr(
                high=self._day_high,
                low=self._day_low,
                close=self._day_close,
            )
            logger.debug(
                "New day %s — CPR: pivot=%.2f tc=%.2f bc=%.2f width_pct=%.4f narrow=%s",
                candle_day, self._cpr.pivot, self._cpr.tc, self._cpr.bc,
                self._cpr.width_pct, self._cpr.is_narrow,
            )

            # Reset day tracking
            self._current_day = candle_day
            self._day_open = candle.open
            self._day_high = candle.high
            self._day_low = candle.low
            self._day_close = candle.close
            self._position = None
            self._traded_today = False
            return

        # ── Update intraday OHLC ────────────────────────────────────
        self._day_high = max(self._day_high, candle.high)
        self._day_low = min(self._day_low, candle.low)
        self._day_close = candle.close

        # ── Need CPR to proceed ─────────────────────────────────────
        if self._cpr is None:
            return

        threshold = self.get_param("narrow_threshold", 0.3)

        # ── Check exits first ───────────────────────────────────────
        if self._position == "LONG":
            if candle.low <= self._stop_loss:
                self._close_position(candle, f"Stop loss hit at {self._stop_loss:.2f}")
            elif candle.high >= self._target:
                self._close_position(candle, f"Target hit at {self._target:.2f}")
            return

        if self._position == "SHORT":
            if candle.high >= self._stop_loss:
                self._close_position(candle, f"Stop loss hit at {self._stop_loss:.2f}")
            elif candle.low <= self._target:
                self._close_position(candle, f"Target hit at {self._target:.2f}")
            return

        # ── Check entry — only on narrow CPR, one trade per day ─────
        if self._traded_today:
            return

        if self._cpr.width_pct >= threshold:
            return  # Not a narrow CPR day

        rr = self.get_param("risk_reward_ratio", 2.0)
        min_sl_pct = self.get_param("min_sl_distance_pct", 0.1)

        decision_log.log("strategy", "debug", "Checking breakout entry", {
            "symbol": self.get_param("trading_symbol"),
            "candle_close": candle.close,
            "tc": self._cpr.tc,
            "bc": self._cpr.bc,
            "width_pct": self._cpr.width_pct,
            "above_tc": candle.close > self._cpr.tc,
            "below_bc": candle.close < self._cpr.bc,
        })

        # LONG breakout: candle closes above TC
        if candle.close > self._cpr.tc:
            sl_distance = candle.close - self._cpr.bc
            # Fix #6: Enforce minimum SL distance
            min_sl_distance = candle.close * (min_sl_pct / 100.0)
            if sl_distance < min_sl_distance:
                sl_distance = min_sl_distance
                decision_log.log("strategy", "warn", "SL distance too small, using floor", {
                    "symbol": self.get_param("trading_symbol"),
                    "original_sl_dist": candle.close - self._cpr.bc,
                    "floor_sl_dist": min_sl_distance,
                })

            self._position = "LONG"
            self._entry_price = candle.close
            self._stop_loss = round(candle.close - sl_distance, 2)
            self._target = candle.close + rr * sl_distance
            self._traded_today = True
            self._order_confirmed = False  # Fix #5: Reset until order confirmed
            self._trailing_peak = candle.close  # Initialize peak at entry

            decision_log.log("strategy", "info", "LONG breakout signal", {
                "symbol": self.get_param("trading_symbol"),
                "entry": self._entry_price, "sl": self._stop_loss,
                "target": self._target, "cpr_width": self._cpr.width_pct,
            })
            self._emit_buy_signal(candle, f"CPR breakout LONG — close {candle.close:.2f} > TC {self._cpr.tc:.2f} (width {self._cpr.width_pct:.4f}%)")
            return

        # SHORT breakout: candle closes below BC
        if candle.close < self._cpr.bc:
            sl_distance = self._cpr.tc - candle.close
            # Fix #6: Enforce minimum SL distance
            min_sl_distance = candle.close * (min_sl_pct / 100.0)
            if sl_distance < min_sl_distance:
                sl_distance = min_sl_distance
                decision_log.log("strategy", "warn", "SL distance too small, using floor", {
                    "symbol": self.get_param("trading_symbol"),
                    "original_sl_dist": self._cpr.tc - candle.close,
                    "floor_sl_dist": min_sl_distance,
                })

            self._position = "SHORT"
            self._entry_price = candle.close
            self._stop_loss = round(candle.close + sl_distance, 2)
            self._target = candle.close - rr * sl_distance
            self._traded_today = True
            self._order_confirmed = False  # Fix #5: Reset until order confirmed
            self._trailing_peak = candle.close  # Initialize trough at entry

            decision_log.log("strategy", "info", "SHORT breakout signal", {
                "symbol": self.get_param("trading_symbol"),
                "entry": self._entry_price, "sl": self._stop_loss,
                "target": self._target, "cpr_width": self._cpr.width_pct,
            })
            self._emit_sell_signal(candle, f"CPR breakout SHORT — close {candle.close:.2f} < BC {self._cpr.bc:.2f} (width {self._cpr.width_pct:.4f}%)")
            return

    # ── Signal helpers ──────────────────────────────────────────────────

    def _emit_buy_signal(self, candle: Candle, reason: str) -> None:
        symbol = self.get_param("trading_symbol", "")
        exchange_str = self.get_param("exchange", "NSE")
        quantity = self.get_param("quantity", 1)

        self._emit_signal(StrategySignal(
            instrument_token=self.get_param("instrument_token", 0),
            trading_symbol=symbol,
            action="BUY",
            reason=reason,
            timestamp=candle.timestamp,
            metadata={
                "cpr_pivot": self._cpr.pivot if self._cpr else 0,
                "cpr_tc": self._cpr.tc if self._cpr else 0,
                "cpr_bc": self._cpr.bc if self._cpr else 0,
                "cpr_width_pct": self._cpr.width_pct if self._cpr else 0,
                "entry_price": self._entry_price,
                "stop_loss": self._stop_loss,
                "target": self._target,
            },
            order_request=OrderRequest(
                tradingsymbol=symbol,
                exchange=Exchange(exchange_str),
                transaction_type=TransactionType.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                product=ProductType.MIS,  # Intraday
                variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

    def _emit_sell_signal(self, candle: Candle, reason: str) -> None:
        symbol = self.get_param("trading_symbol", "")
        exchange_str = self.get_param("exchange", "NSE")
        quantity = self.get_param("quantity", 1)

        self._emit_signal(StrategySignal(
            instrument_token=self.get_param("instrument_token", 0),
            trading_symbol=symbol,
            action="SELL",
            reason=reason,
            timestamp=candle.timestamp,
            metadata={
                "cpr_pivot": self._cpr.pivot if self._cpr else 0,
                "cpr_tc": self._cpr.tc if self._cpr else 0,
                "cpr_bc": self._cpr.bc if self._cpr else 0,
                "cpr_width_pct": self._cpr.width_pct if self._cpr else 0,
                "entry_price": self._entry_price,
                "stop_loss": self._stop_loss,
                "target": self._target,
            },
            order_request=OrderRequest(
                tradingsymbol=symbol,
                exchange=Exchange(exchange_str),
                transaction_type=TransactionType.SELL,
                order_type=OrderType.MARKET,
                quantity=quantity,
                product=ProductType.MIS,
                variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

    def _close_position(self, candle: Candle, reason: str) -> None:
        """Emit a closing signal (opposite direction) and reset position."""
        if self._position == "LONG":
            self._emit_sell_signal(candle, reason)
        elif self._position == "SHORT":
            self._emit_buy_signal(candle, reason)

        self._position = None
        self._entry_price = 0.0
        self._stop_loss = 0.0
        self._target = 0.0
        self._trailing_peak = 0.0
        self._order_confirmed = False

    def _close_position_at_price(self, price: float, ts: datetime, reason: str) -> None:
        """Emit a closing signal from a tick (no candle available) and reset position."""
        symbol = self.get_param("trading_symbol", "")
        exchange_str = self.get_param("exchange", "NSE")
        quantity = self.get_param("quantity", 1)

        if self._position == "LONG":
            action = "SELL"
            tx_type = TransactionType.SELL
        elif self._position == "SHORT":
            action = "BUY"
            tx_type = TransactionType.BUY
        else:
            return

        self._emit_signal(StrategySignal(
            instrument_token=self.get_param("instrument_token", 0),
            trading_symbol=symbol,
            action=action,
            reason=reason,
            timestamp=ts,
            metadata={
                "cpr_pivot": self._cpr.pivot if self._cpr else 0,
                "cpr_tc": self._cpr.tc if self._cpr else 0,
                "cpr_bc": self._cpr.bc if self._cpr else 0,
                "cpr_width_pct": self._cpr.width_pct if self._cpr else 0,
                "exit_price": price,
                "entry_price": self._entry_price,
                "stop_loss": self._stop_loss,
                "target": self._target,
                "exit_source": "tick",
            },
            order_request=OrderRequest(
                tradingsymbol=symbol,
                exchange=Exchange(exchange_str),
                transaction_type=tx_type,
                order_type=OrderType.MARKET,
                quantity=quantity,
                product=ProductType.MIS,
                variety=Variety.REGULAR,
                validity=Validity.DAY,
            ),
        ))

        self._position = None
        self._entry_price = 0.0
        self._stop_loss = 0.0
        self._target = 0.0
        self._trailing_peak = 0.0
        self._order_confirmed = False

    # ── Public accessors for scanner ────────────────────────────────────

    def get_cpr(self) -> CPRLevels | None:
        """Return the current day's CPR levels (computed from previous day)."""
        return self._cpr

    def get_prev_day_ohlc(self) -> dict[str, float] | None:
        """Return the previous day's OHLC used to compute current CPR."""
        return self._prev_day_ohlc
