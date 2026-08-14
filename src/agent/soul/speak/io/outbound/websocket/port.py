from __future__ import annotations

import asyncio
from typing import Any

from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent


class WebSocketSpeakStreamPort:
    """SpeakStreamEvent → asyncio.Queue 帧；只做编码与线程安全投递，不含 session 路由。"""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        queue: asyncio.Queue,
        *,
        gen_id: str,
    ) -> None:
        self._loop = loop
        self._queue = queue
        self._gen_id = gen_id
        self._closed = False

    def close(self) -> None:
        self._closed = True
        self._loop.call_soon_threadsafe(
            self._queue.put_nowait,
            {"type": "__port_closed__"},
        )

    def emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self._closed:
            return
        payload: dict[str, Any] = {
            "type": "speak_event",
            "gen_id": self._gen_id,
            "session_id": session_id,
            "kind": event.kind,
            "text": event.text,
            "final": event.final,
            "meta": dict(event.meta),
        }
        self._loop.call_soon_threadsafe(self._queue.put_nowait, payload)
