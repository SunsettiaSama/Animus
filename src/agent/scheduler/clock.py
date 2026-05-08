from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from agent.scheduler.config import SchedulerConfig
from agent.scheduler.runner import TaskRunner
from agent.scheduler.store import TaskStore

logger = logging.getLogger(__name__)


class TemporalClock:
    """Independent clock thread with its own asyncio event loop.

    Completely isolated from the uvicorn main loop — tick precision is
    unaffected by HTTP/SSE/WebSocket load on the application side.

    Usage::

        clock = TemporalClock(cfg, store, runner)
        clock.start()   # non-blocking, spawns daemon thread
        ...
        clock.stop()    # signals the loop to stop
    """

    def __init__(
        self,
        cfg: SchedulerConfig,
        store: TaskStore,
        runner: TaskRunner,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._runner = runner
        self._stopped = False
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="temporal-clock",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped = True
        self._loop.call_soon_threadsafe(self._loop.stop)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._tick_loop())

    async def _tick_loop(self) -> None:
        recovered = self._store.reset_stale_running()
        if recovered:
            logger.info("[TemporalClock] recovered %d stale running task(s) → pending", recovered)

        while not self._stopped:
            now = datetime.now(timezone.utc)
            for task in self._store.get_due_tasks(now):
                t = asyncio.create_task(
                    self._runner.run(task, self._store),
                    name=f"scheduler:{task.id[:8]}",
                )
                t.add_done_callback(self._on_task_done)
            await asyncio.sleep(self._cfg.poll_interval)

    def _on_task_done(self, t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[TemporalClock] task coroutine raised: %s", exc)
