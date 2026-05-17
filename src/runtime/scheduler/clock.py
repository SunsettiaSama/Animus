from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from runtime.scheduler.config import SchedulerConfig
from runtime.scheduler.store import TaskStore
from runtime.scheduler.task import TaskStatus

if TYPE_CHECKING:
    from runtime.scheduler.executor import TaskExecutorProtocol
    from runtime.scheduler.heartbeat_iface import HeartbeatProtocol

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class TemporalClock:
    """Independent clock thread with its own asyncio event loop.

    Completely isolated from the uvicorn main loop — tick precision is
    unaffected by HTTP/SSE/WebSocket load on the application side.

    ``executor`` implements TaskExecutorProtocol (agent's TaskRunner).
    ``heartbeat`` implements HeartbeatProtocol (agent's HeartbeatModule); optional.
    """

    def __init__(
        self,
        cfg: SchedulerConfig,
        store: TaskStore,
        executor: "TaskExecutorProtocol",
        heartbeat: "HeartbeatProtocol | None" = None,
    ) -> None:
        self._cfg = cfg
        self._store = store
        self._executor = executor
        self._heartbeat = heartbeat
        self._stopped = False
        self._paused = False
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
        self._stopped = True
        if not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_running(self) -> bool:
        return not self._stopped and self._thread.is_alive()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    # ── Internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._tick_loop(), name="temporal-clock-tick")
        self._loop.run_forever()

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

        _last_proactive = _EPOCH
        if self._heartbeat is not None:
            recent = self._heartbeat.recent_log(1)
            if recent:
                try:
                    _last_proactive = datetime.fromisoformat(recent[0]["ts"])
                except (KeyError, ValueError):
                    pass

        _last_cleanup = _EPOCH

        while not self._stopped:
            if not self._paused:
                now = datetime.now(timezone.utc)

                # ① max_concurrent guard
                running_count = sum(
                    1 for t in self._store.list_all()
                    if t.status == TaskStatus.running
                )
                if running_count < self._cfg.max_concurrent:
                    for task in self._store.get_due_tasks(now):
                        t = asyncio.create_task(
                            self._executor.run(task, self._store),
                            name=f"scheduler:{task.id[:8]}",
                        )
                        t.add_done_callback(self._on_task_done)

                # ② proactive heartbeat timer — uses pending_force via Protocol
                if (
                    self._heartbeat is not None
                    and self._cfg.heartbeat.clock_drives_heartbeat
                ):
                    hb_interval = self._cfg.heartbeat.interval
                    force = self._heartbeat.pending_force
                    elapsed = (now - _last_proactive).total_seconds()
                    if hb_interval > 0 and (force or elapsed >= hb_interval):
                        _last_proactive = now
                        asyncio.create_task(
                            asyncio.to_thread(self._heartbeat.tick),
                            name="heartbeat-tick",
                        )

                # ③ daily retention cleanup
                retention = self._cfg.task_retention_days
                if (now - _last_cleanup).total_seconds() >= 86400:
                    _last_cleanup = now
                    if retention > 0:
                        asyncio.create_task(
                            asyncio.to_thread(self._store.cleanup_old_tasks, retention),
                            name="scheduler-cleanup",
                        )

            await asyncio.sleep(self._cfg.poll_interval)

    def _on_task_done(self, t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("[TemporalClock] task coroutine raised: %s", exc)
