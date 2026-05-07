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

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            question = await self._queue.get()
            self._last_active = time.time()
            logger.info("[AgentSession] %s ← %r", self._id, question[:80])
            answer = await loop.run_in_executor(
                self._executor,
                self._process_sync,
                question,
            )
            if answer:
                logger.info("[AgentSession] %s → %r", self._id, answer[:80])
                await self._reply_fn(answer)
            else:
                logger.warning("[AgentSession] %s got empty answer for %r", self._id, question[:80])

    def _process_sync(self, question: str) -> str:
        from agent.react.tao import FinishEvent, StepEvent
        answer = ""
        summaries: list[str] = []
        for event in self._conv.stream(question):
            if isinstance(event, StepEvent) and event.thought:
                # Collect a brief thought snippet (≤40 chars) for each reasoning step.
                snippet = event.thought.strip()[:40].rstrip()
                if len(event.thought.strip()) > 40:
                    snippet += "…"
                summaries.append(snippet)
            elif isinstance(event, FinishEvent):
                answer = event.answer
                break
        self._conv.post_process()
        if summaries and answer:
            chain = " → ".join(f"[{i + 1}] {s}" for i, s in enumerate(summaries))
            answer = f"💭 {chain}\n\n{answer}"
        return answer
