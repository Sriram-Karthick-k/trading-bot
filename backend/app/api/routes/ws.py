"""
WebSocket endpoint for real-time streaming.

Supports two types of data:
1. Tick data — instrument-level price ticks (subscription-based)
2. Engine events — trading engine status/events (broadcast to all subscribers)

Client actions:
  {"action": "subscribe", "tokens": [int, ...]}     — subscribe to tick tokens
  {"action": "unsubscribe", "tokens": [int, ...]}   — unsubscribe from tokens
  {"action": "subscribe_engine"}                     — subscribe to engine events
  {"action": "unsubscribe_engine"}                   — unsubscribe from engine events
  {"action": "ping"}                                 — keepalive

Server messages:
  {"type": "subscribed", "tokens": [...]}            — subscription ack
  {"type": "unsubscribed", "tokens": [...]}          — unsubscription ack
  {"type": "engine_subscribed"}                      — engine subscription ack
  {"type": "engine_unsubscribed"}                    — engine unsubscription ack
  {"type": "pong"}                                   — keepalive response
  {"type": "tick", ...}                              — tick data
  {"type": "engine_event", ...}                      — engine event
  {"type": "engine_status", ...}                     — engine status snapshot
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections for tick and engine event streaming."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[int]] = {}  # conn_id → instrument tokens
        self._engine_subscribers: set[str] = set()       # conn_ids subscribed to engine events

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._connections[client_id] = websocket
        self._subscriptions[client_id] = set()
        logger.info("WebSocket connected: %s", client_id)

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)
        self._subscriptions.pop(client_id, None)
        self._engine_subscribers.discard(client_id)
        logger.info("WebSocket disconnected: %s", client_id)

    def subscribe(self, client_id: str, tokens: list[int]) -> None:
        if client_id in self._subscriptions:
            self._subscriptions[client_id].update(tokens)

    def unsubscribe(self, client_id: str, tokens: list[int]) -> None:
        if client_id in self._subscriptions:
            self._subscriptions[client_id] -= set(tokens)

    def subscribe_engine(self, client_id: str) -> None:
        """Subscribe a client to engine event broadcasts."""
        self._engine_subscribers.add(client_id)

    def unsubscribe_engine(self, client_id: str) -> None:
        """Unsubscribe a client from engine event broadcasts."""
        self._engine_subscribers.discard(client_id)

    async def broadcast_tick(self, instrument_token: int, data: dict[str, Any]) -> None:
        """Send tick data to all clients subscribed to this instrument token."""
        disconnected: list[str] = []
        payload = {"type": "tick", **data}
        for client_id, tokens in self._subscriptions.items():
            if instrument_token in tokens:
                ws = self._connections.get(client_id)
                if ws:
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    async def broadcast_engine_event(self, event: dict[str, Any]) -> None:
        """Send an engine event to all engine-subscribed clients."""
        if not self._engine_subscribers:
            return

        payload = {"type": "engine_event", "event": event}
        disconnected: list[str] = []
        for client_id in self._engine_subscribers:
            ws = self._connections.get(client_id)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception:
                    disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    async def broadcast_engine_status(self, status: dict[str, Any]) -> None:
        """Send engine status snapshot to all engine-subscribed clients."""
        if not self._engine_subscribers:
            return

        payload = {"type": "engine_status", "status": status}
        disconnected: list[str] = []
        for client_id in self._engine_subscribers:
            ws = self._connections.get(client_id)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception:
                    disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    async def broadcast_data(self, data_type: str, data: Any) -> None:
        """
        Send arbitrary typed data to all engine-subscribed clients.

        Used for pushing orders, positions, risk status, and strategies
        updates so the frontend doesn't need to poll.

        Message format: {"type": data_type, "data": data}
        """
        if not self._engine_subscribers:
            return

        payload = {"type": data_type, "data": data}
        disconnected: list[str] = []
        for client_id in self._engine_subscribers:
            ws = self._connections.get(client_id)
            if ws:
                try:
                    await ws.send_json(payload)
                except Exception:
                    disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    @property
    def active_connections(self) -> int:
        return len(self._connections)

    @property
    def engine_subscriber_count(self) -> int:
        return len(self._engine_subscribers)


manager = ConnectionManager()


@router.websocket("/ws/ticks/{client_id}")
async def websocket_ticks(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")

            if action == "subscribe":
                tokens = data.get("tokens", [])
                manager.subscribe(client_id, tokens)
                await websocket.send_json({"type": "subscribed", "tokens": tokens})

            elif action == "unsubscribe":
                tokens = data.get("tokens", [])
                manager.unsubscribe(client_id, tokens)
                await websocket.send_json({"type": "unsubscribed", "tokens": tokens})

            elif action == "subscribe_engine":
                manager.subscribe_engine(client_id)
                await websocket.send_json({"type": "engine_subscribed"})

            elif action == "unsubscribe_engine":
                manager.unsubscribe_engine(client_id)
                await websocket.send_json({"type": "engine_unsubscribed"})

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", client_id, e)
        manager.disconnect(client_id)
