"""
WebSocket endpoint for real-time tick data streaming.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages WebSocket connections for tick streaming."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._subscriptions: dict[str, set[int]] = {}  # conn_id → instrument tokens

    async def connect(self, websocket: WebSocket, client_id: str) -> None:
        await websocket.accept()
        self._connections[client_id] = websocket
        self._subscriptions[client_id] = set()
        logger.info("WebSocket connected: %s", client_id)

    def disconnect(self, client_id: str) -> None:
        self._connections.pop(client_id, None)
        self._subscriptions.pop(client_id, None)
        logger.info("WebSocket disconnected: %s", client_id)

    def subscribe(self, client_id: str, tokens: list[int]) -> None:
        if client_id in self._subscriptions:
            self._subscriptions[client_id].update(tokens)

    def unsubscribe(self, client_id: str, tokens: list[int]) -> None:
        if client_id in self._subscriptions:
            self._subscriptions[client_id] -= set(tokens)

    async def broadcast_tick(self, instrument_token: int, data: dict[str, Any]) -> None:
        disconnected: list[str] = []
        for client_id, tokens in self._subscriptions.items():
            if instrument_token in tokens:
                ws = self._connections.get(client_id)
                if ws:
                    try:
                        await ws.send_json(data)
                    except Exception:
                        disconnected.append(client_id)
        for cid in disconnected:
            self.disconnect(cid)

    @property
    def active_connections(self) -> int:
        return len(self._connections)


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

            elif action == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(client_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", client_id, e)
        manager.disconnect(client_id)
