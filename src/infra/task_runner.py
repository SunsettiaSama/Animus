from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any


class BackgroundTaskRunner:
    """Shared thread-pool executor with a named task registry.

    Replaces the per-connection ``ThreadPoolExecutor(max_workers=1)`` and
    ad-hoc ``threading.Thread(daemon=True)`` calls scattered throughout
    ``app.py``.  A single instance lives for the lifetime of the server
    process and is shut down gracefully in the FastAPI ``shutdown`` event.

    Usage::

        runner = BackgroundTaskRunner(max_workers=8)
        runner.submit("preload", tao.preload)
        runner.submit("post_process", fn, on_error=lambda e: log(e))
        runner.shutdown()
    """

    def __init__(self, max_workers: int = 8) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bg")
        self._tasks: dict[str, Future] = {}
        self._lock = threading.Lock()

    # ── Submit ────────────────────────────────────────────────────────────────

    def submit(
        self,
        name: str,
        fn: Callable,
        *args: Any,
        on_error: Callable[[BaseException], None] | None = None,
    ) -> Future:
        future = self._executor.submit(fn, *args)

        def _done(f: Future) -> None:
            exc = f.exception()
            if exc is not None and on_error is not None:
                on_error(exc)

        future.add_done_callback(_done)

        with self._lock:
            self._tasks[name] = future

        return future

    # ── Introspection ─────────────────────────────────────────────────────────

    def status(self) -> dict[str, str]:
        with self._lock:
            snapshot = dict(self._tasks)
        result: dict[str, str] = {}
        for name, f in snapshot.items():
            if f.running():
                result[name] = "running"
            elif f.cancelled():
                result[name] = "cancelled"
            elif f.exception() is not None:
                result[name] = "error"
            else:
                result[name] = "done"
        return result

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def shutdown(self, wait: bool = True, timeout: float = 15.0) -> None:
        """Gracefully stop accepting new tasks and drain running ones.

        ``timeout`` is applied per-future when ``wait=True`` to avoid blocking
        the shutdown handler indefinitely.
        """
        if wait:
            with self._lock:
                futures = list(self._tasks.values())
            for f in futures:
                if not f.done():
                    f.result(timeout=timeout)
        self._executor.shutdown(wait=wait)
