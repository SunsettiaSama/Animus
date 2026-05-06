from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from .base import BaseTransport

logger = logging.getLogger(__name__)


class ForwardWSTransport(BaseTransport):
    """Active WebSocket client that connects to an OneBot 11 WS server.

    Frame protocol (NapCat / go-cqhttp forward-WS mode):
    - Frame with ``echo`` field  → action response; resolves the matching Future
    - Frame without ``echo``     → event frame; forwarded to on_event callback
    - Outgoing action frame      → {"action": ..., "params": ..., "echo": <uuid>}

    Reconnect: exponential back-off up to ``_MAX_INTERVAL`` seconds.
    """

    _MAX_INTERVAL: float = 60.0

    def __init__(
        self,
        url: str,
        access_token: str = "",
        reconnect_interval: float = 5.0,
    ) -> None:
        super().__init__()
        self._url = url
        self._access_token = access_token
        self._base_interval = reconnect_interval

        self._ws: Any = None                          # websockets.WebSocketClientProtocol
        self._pending: dict[str, asyncio.Future] = {}
        self._state: str = "stopped"                  # stopped | connecting | running | error
        self._connect_task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── BaseTransport ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self._state = "connecting"
        self._connect_task = asyncio.create_task(self._connect_loop())

    async def stop(self) -> None:
        self._state = "stopped"
        if self._stop_event is not None:
            self._stop_event.set()
        if self._connect_task is not None:
            self._connect_task.cancel()
            try:
                await self._connect_task
            except (asyncio.CancelledError, Exception):
                pass
            self._connect_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def call_action(
        self,
        action: str,
        params: dict,
        timeout: float = 10.0,
    ) -> dict:
        if self._ws is None or self._state != "running":
            raise RuntimeError(f"Transport not connected (state={self._state})")
        echo = str(uuid.uuid4())
        loop = self._loop or asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[echo] = fut
        payload = json.dumps({"action": action, "params": params, "echo": echo})
        await self._ws.send(payload)
        return await asyncio.wait_for(fut, timeout)

    def status(self) -> dict:
        return {"state": self._state, "url": self._url}

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _connect_loop(self) -> None:
        interval = self._base_interval
        assert self._stop_event is not None

        while not self._stop_event.is_set():
            try:
                await self._connect_and_recv()
                interval = self._base_interval  # reset on clean exit
            except asyncio.CancelledError:
                return
            except Exception as exc:
                self._state = "error"
                logger.warning("[ForwardWS] disconnected (%s), retry in %.0fs", exc, interval)

            if self._stop_event.is_set():
                return
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                return  # stop was requested during sleep
            except asyncio.TimeoutError:
                pass
            interval = min(interval * 1.5, self._MAX_INTERVAL)
            self._state = "connecting"

    async def _connect_and_recv(self) -> None:
        import websockets  # type: ignore[import]

        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        async with websockets.connect(self._url, additional_headers=headers) as ws:
            self._ws = ws
            self._state = "running"
            logger.info("[ForwardWS] connected to %s", self._url)
            async for raw_text in ws:
                frame: dict = json.loads(raw_text)
                echo = frame.get("echo")
                if echo and echo in self._pending:
                    fut = self._pending.pop(echo)
                    if not fut.done():
                        fut.set_result(frame)
                elif self.on_event is not None:
                    await self.on_event(frame)
        self._ws = None

    def __repr__(self) -> str:
        return f"<ForwardWSTransport url={self._url!r} state={self._state}>"
