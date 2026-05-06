from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable


class BaseTransport(ABC):
    """Two-way OneBot 11 communication abstraction.

    Incoming frames → on_event callback (injected by consumer).
    Outgoing actions → call_action().
    """

    def __init__(self) -> None:
        self.on_event: Callable[[dict], Awaitable[None]] | None = None

    @abstractmethod
    async def start(self) -> None:
        """Begin listening/connecting.  Must be non-blocking (return immediately)."""
        raise NotImplementedError

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down."""
        raise NotImplementedError

    @abstractmethod
    async def call_action(
        self,
        action: str,
        params: dict,
        timeout: float = 10.0,
    ) -> dict:
        """Send an action to the server and await the response."""
        raise NotImplementedError

    @abstractmethod
    def status(self) -> dict:
        """Return a dict with at least a ``"state"`` key."""
        raise NotImplementedError
