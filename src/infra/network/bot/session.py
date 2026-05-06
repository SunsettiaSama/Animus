from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class AgentSession:
    """Per-user / per-group conversation session.

    Messages are strictly serialised within a single session (asyncio.Queue)
    while different sessions run concurrently.  ConvLoop.stream() is
    synchronous and runs inside a ThreadPoolExecutor to avoid blocking the
    event loop.
    """

    def __init__(
        self,
        session_id: str,
        conv_loop: Any,          # ConvLoop
        reply_fn: Callable[[str], Awaitable[None]],
        executor: ThreadPoolExecutor,
    ) -> None:
        self._id       = session_id
        self._conv     = conv_loop
        self._reply_fn = reply_fn
        self._executor = executor
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()

    @property
    def session_id(self) -> str:
        return self._id

    @property
    def last_active(self) -> float:
        return self._last_active

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn the background consumer task."""
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_forever(), name=f"session:{self._id}")

    async def enqueue(self, text: str) -> None:
        self._last_active = time.time()
        await self._queue.put(text)

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            question = await self._queue.get()
            self._last_active = time.time()
            answer = await loop.run_in_executor(
                self._executor,
                self._process_sync,
                question,
            )
            if answer:
                await self._reply_fn(answer)

    def _process_sync(self, question: str) -> str:
        from agent.react.tao import FinishEvent
        answer = ""
        for event in self._conv.stream(question):
            if isinstance(event, FinishEvent):
                answer = event.answer
                break
        self._conv.post_process()
        return answer
