from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class ReplyTarget:
    channel: str
    params: dict = field(default_factory=dict)

    @classmethod
    def from_task_dict(cls, d: dict | None) -> ReplyTarget | None:
        if d is None:
            return None
        channel = d.get("type", "webui")
        params = {k: v for k, v in d.items() if k != "type"}
        return cls(channel=channel, params=params)

    def to_task_dict(self) -> dict:
        return {"type": self.channel, **self.params}


class ChannelRouter:
    """Registry of delivery functions keyed by channel name.

    Each channel registers a callable with the signature:
        fn(target: ReplyTarget, title: str, message: str) -> None

    All registration and delivery calls are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: dict[str, Callable[[ReplyTarget, str, str], None]] = {}

    def register(self, channel: str, fn: Callable[[ReplyTarget, str, str], None]) -> None:
        with self._lock:
            self._handlers[channel] = fn
        logger.debug("[ChannelRouter] registered channel %r", channel)

    def unregister(self, channel: str) -> None:
        with self._lock:
            self._handlers.pop(channel, None)

    def deliver(self, target: ReplyTarget, title: str, message: str) -> None:
        with self._lock:
            fn = self._handlers.get(target.channel)
        if fn is None:
            logger.warning("[ChannelRouter] no handler for channel %r — message dropped", target.channel)
            return
        fn(target, title, message)

    def available_channels(self) -> list[str]:
        with self._lock:
            return list(self._handlers.keys())
