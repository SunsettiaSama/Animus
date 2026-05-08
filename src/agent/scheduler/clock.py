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

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the clock to stop and block until the thread exits."""
        self._stopped = True
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        """Thread entry point.

        Runs _tick_loop as a Task inside run_forever() so that loop.stop()
        from the main thread returns cleanly without raising
        'Event loop stopped before Future completed'.  After the loop exits,
        any pending tasks (e.g. in-flight scheduler coroutines) are cancelled
        and awaited before the loop is closed.
        """
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._tick_loop(), name="temporal-clock-tick")
        self._loop.run_forever()

        # Cancel any tasks that were still running when loop.stop() was called.
        pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
        if pending:
            for t in pending:
                t.cancel()
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))

        self._loop.close()

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
