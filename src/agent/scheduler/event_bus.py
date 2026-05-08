from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Thread-safe pub/sub bridge between the Clock thread and the main asyncio loop.

    Clock thread calls ``publish``; main-loop coroutines register with ``subscribe``.
    When a main loop is registered, handlers are dispatched via
    ``loop.call_soon_threadsafe`` so they always run on the correct loop.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._handlers: dict[str, list[Callable]] = {}
        self._main_loop: asyncio.AbstractEventLoop | None = None

    def set_main_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._main_loop = loop

    def subscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        with self._lock:
            bucket = self._handlers.get(event_type, [])
            if handler in bucket:
                bucket.remove(handler)

    def publish(self, event_type: str, payload: dict) -> None:
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
        if not handlers:
            return
        loop = self._main_loop
        for h in handlers:
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(h, event_type, payload)
            else:
                try:
                    h(event_type, payload)
                except Exception as exc:
                    logger.error("[EventBus] handler error for %s: %s", event_type, exc)
