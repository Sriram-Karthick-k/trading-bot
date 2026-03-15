"""
Zerodha KiteTicker WebSocket wrapper.

Converts KiteTicker events to provider-agnostic TickData types.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.providers.types import TickData, TickMode
from app.providers.zerodha.mapper import ZerodhaMapper

logger = logging.getLogger(__name__)


class ZerodhaTicker:
    """
    Wraps KiteTicker to implement the TickerConnection protocol.

    Usage:
        ticker = ZerodhaTicker(api_key, access_token)
        ticker.set_on_tick(my_callback)
        ticker.connect()
        ticker.subscribe([408065, 884737], TickMode.QUOTE)
    """

    def __init__(self, api_key: str, access_token: str):
        self._api_key = api_key
        self._access_token = access_token
        self._mapper = ZerodhaMapper()
        self._kws = None
        self._connected = False

        # Callbacks
        self._on_tick: Callable[[list[TickData]], None] | None = None
        self._on_order_update: Callable[[dict], None] | None = None
        self._on_connect_cb: Callable[[], None] | None = None
        self._on_disconnect_cb: Callable[[int, str | None], None] | None = None
        self._on_error_cb: Callable[[Exception], None] | None = None

        # Subscription state
        self._subscriptions: dict[int, TickMode] = {}

    def _init_kws(self) -> Any:
        try:
            from kiteconnect import KiteTicker
            kws = KiteTicker(self._api_key, self._access_token)

            kws.on_ticks = self._handle_ticks
            kws.on_connect = self._handle_connect
            kws.on_close = self._handle_disconnect
            kws.on_error = self._handle_error
            kws.on_order_update = self._handle_order_update

            return kws
        except ImportError:
            raise ImportError("kiteconnect package required. Run: pip install kiteconnect")

    def connect(self) -> None:
        self._kws = self._init_kws()
        self._kws.connect(threaded=True)

    def disconnect(self) -> None:
        if self._kws:
            self._kws.close()
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, instrument_tokens: list[int], mode: TickMode = TickMode.QUOTE) -> None:
        if self._kws and self._connected:
            self._kws.subscribe(instrument_tokens)
            self._kws.set_mode(self._kws.MODE_FULL if mode == TickMode.FULL
                               else self._kws.MODE_QUOTE if mode == TickMode.QUOTE
                               else self._kws.MODE_LTP,
                               instrument_tokens)
        for token in instrument_tokens:
            self._subscriptions[token] = mode

    def unsubscribe(self, instrument_tokens: list[int]) -> None:
        if self._kws and self._connected:
            self._kws.unsubscribe(instrument_tokens)
        for token in instrument_tokens:
            self._subscriptions.pop(token, None)

    def set_on_tick(self, callback: Callable[[list[TickData]], None]) -> None:
        self._on_tick = callback

    def set_on_order_update(self, callback: Callable[[dict], None]) -> None:
        self._on_order_update = callback

    def set_on_connect(self, callback: Callable[[], None]) -> None:
        self._on_connect_cb = callback

    def set_on_disconnect(self, callback: Callable[[int, str | None], None]) -> None:
        self._on_disconnect_cb = callback

    def set_on_error(self, callback: Callable[[Exception], None]) -> None:
        self._on_error_cb = callback

    # ─── Internal handlers ────────────────────────────────────────────────

    def _handle_ticks(self, ws: Any, ticks: list[dict]) -> None:
        if self._on_tick:
            converted = [self._mapper.to_tick_data(t) for t in ticks]
            self._on_tick(converted)

    def _handle_connect(self, ws: Any, response: Any) -> None:
        self._connected = True
        logger.info("KiteTicker connected")
        # Re-subscribe to all instruments
        if self._subscriptions:
            tokens_by_mode: dict[TickMode, list[int]] = {}
            for token, mode in self._subscriptions.items():
                tokens_by_mode.setdefault(mode, []).append(token)
            for mode, tokens in tokens_by_mode.items():
                self.subscribe(tokens, mode)
        if self._on_connect_cb:
            self._on_connect_cb()

    def _handle_disconnect(self, ws: Any, code: int, reason: str | None) -> None:
        self._connected = False
        logger.warning("KiteTicker disconnected: code=%s reason=%s", code, reason)
        if self._on_disconnect_cb:
            self._on_disconnect_cb(code, reason)

    def _handle_error(self, ws: Any, code: int, reason: str) -> None:
        logger.error("KiteTicker error: code=%s reason=%s", code, reason)
        if self._on_error_cb:
            self._on_error_cb(Exception(f"KiteTicker error {code}: {reason}"))

    def _handle_order_update(self, ws: Any, data: dict) -> None:
        if self._on_order_update:
            self._on_order_update(data)
