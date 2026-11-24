"""In-process pub/sub hub that fans out automation events to WebSocket clients."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Set

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._clients: Dict[int, Set[WebSocket]] = defaultdict(set)
        self._buffers: Dict[int, Deque[dict[str, Any]]] = defaultdict(lambda: deque(maxlen=80))
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients[user_id].add(ws)
        for event in list(self._buffers[user_id])[-15:]:
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                break

    async def disconnect(self, user_id: int, ws: WebSocket) -> None:
        async with self._lock:
            self._clients[user_id].discard(ws)

    async def publish(self, user_id: int, event_type: str, payload: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "payload": payload or {}}
        self._buffers[user_id].append(event)
        for ws in list(self._clients.get(user_id, set())):
            try:
                await ws.send_text(json.dumps(event))
            except Exception:
                await self.disconnect(user_id, ws)

    def publish_soon(self, user_id: int, event_type: str, payload: dict[str, Any] | None = None) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.publish(user_id, event_type, payload))


hub = EventHub()


def emit(user_id: int | None, event_type: str, payload: dict[str, Any] | None = None) -> None:
    if user_id is None:
        return
    hub.publish_soon(user_id, event_type, payload)
