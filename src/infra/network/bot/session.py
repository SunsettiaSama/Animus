from __future__ import annotations

import asyncio
import functools
import logging
import queue
import threading
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

    Progressive delivery: the BotTaoAdapter translates TaoEvents into plain
    strings which are placed into _send_queue (non-blocking) and delivered by
    a dedicated _send_thread, so tao reasoning continues without waiting for
    the QQ API round-trip.
    """

    def __init__(
        self,
        session_id: str,
        adapter: Any,            # BotTaoAdapter
        reply_fn: Callable[[str], Awaitable[None]],
        executor: ThreadPoolExecutor,
    ) -> None:
        self._id       = session_id
        self._adapter  = adapter
        self._reply_fn = reply_fn
        self._executor = executor
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._last_active: float = time.time()

        self._send_queue: queue.Queue[str | None] = queue.Queue()
        self._send_thread: threading.Thread | None = None

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
        self._task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "[AgentSession] session %s crashed, restarting: %s",
            self._id, exc, exc_info=exc,
        )
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._run_forever(), name=f"session:{self._id}")
        self._task.add_done_callback(self._on_task_done)

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
        self._send_queue.put(None)
        if self._send_thread is not None:
            self._send_thread.join(timeout=5)
            self._send_thread = None

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        # Stop any leftover send thread from a previous run (e.g. after crash-restart).
        if self._send_thread is not None and self._send_thread.is_alive():
            self._send_queue.put(None)
            self._send_thread.join(timeout=5)
        self._send_queue = queue.Queue()
        self._send_thread = threading.Thread(
            target=self._send_loop,
            args=(loop,),
            daemon=True,
            name=f"bot-send:{self._id}",
        )
        self._send_thread.start()

        while True:
            question = await self._queue.get()
            self._last_active = time.time()

            # 若发送线程意外崩溃（如 QQ API 超时超出重试），在处理下一条前重建它
            if self._send_thread is not None and not self._send_thread.is_alive():
                logger.warning(
                    "[AgentSession] %s send-thread died, restarting before next turn", self._id
                )
                self._send_queue = queue.Queue()
                self._send_thread = threading.Thread(
                    target=self._send_loop,
                    args=(loop,),
                    daemon=True,
                    name=f"bot-send:{self._id}",
                )
                self._send_thread.start()

            logger.info("[AgentSession] %s ← %r", self._id, question[:80])
            await loop.run_in_executor(
                self._executor,
                functools.partial(self._process_sync, question),
            )

    def _send_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Dedicated thread: drain _send_queue and deliver each message via reply_fn."""
        while True:
            text = self._send_queue.get()
            if text is None:
                break
            logger.info("[AgentSession] %s → %r", self._id, text[:80])
            future = asyncio.run_coroutine_threadsafe(self._reply_fn(text), loop)
            try:
                future.result()
            except Exception as exc:
                logger.error(
                    "[AgentSession] %s send failed, skipping: %s", self._id, exc
                )

    def _process_sync(self, question: str) -> str:
        """Run the agent loop via BotTaoAdapter and queue messages for delivery.

        The adapter converts TaoEvents into plain strings; this method only
        handles the threading/delivery layer and has no knowledge of TaoEvent
        concrete types.
        """
        for text in self._adapter.messages(question):
            self._send_queue.put(text)
        return ""
