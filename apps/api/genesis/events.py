"""Event bus bridging the orchestrator thread to WebSocket subscribers.

The orchestrator runs in a plain background thread. It publishes events with
`publish()`, which hops onto the API's asyncio loop via `call_soon_threadsafe`
and fans out to every subscriber of that run.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Bounded so a slow/dead client cannot grow memory without limit.
_QUEUE_MAXSIZE = 512


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Called once at API startup from the asyncio loop."""
        self._loop = loop

    # -- subscription (asyncio side) ---------------------------------------
    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                self._subscribers.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(run_id, ()))

    # -- publishing (any thread) -------------------------------------------
    def publish(self, run_id: str, payload: dict[str, Any]) -> None:
        """Thread-safe fan-out. Safe to call before any client connects."""
        payload.setdefault("ts", datetime.now(timezone.utc).isoformat())
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._dispatch, run_id, payload)
        except RuntimeError:
            # Loop shut down mid-publish; nothing to deliver to.
            pass

    def _dispatch(self, run_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            queues = list(self._subscribers.get(run_id, ()))
        for queue in queues:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop the oldest item to keep the live stream current.
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    logger.debug("dropping event for saturated subscriber")


bus = EventBus()
