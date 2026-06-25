from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Callable

_WAKE_POLL_SEC = 0.5


class DomainWorker:
    """单域 FIFO 队列 + 单消费线程。写路径统一经 enqueue / submit。"""

    def __init__(self, name: str) -> None:
        self._name = name
        self._tasks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return self._name

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        t = threading.Thread(target=self._run, name=self._name, daemon=True)
        t.start()
        self._thread = t

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=30.0)
            self._thread = None

    def status(self) -> dict:
        alive = self._thread is not None and self._thread.is_alive()
        with self._lock:
            queued = len(self._tasks)
        return {
            "state": "running" if alive else "stopped",
            "queued": queued,
        }

    def enqueue(self, task: Callable[[], None]) -> None:
        with self._lock:
            self._tasks.append(task)
        self._wake.set()

    def submit(self, task: Callable[[], object]) -> Future:
        future: Future = Future()

        def _wrapper() -> None:
            if future.cancelled():
                return
            try:
                future.set_result(task())
            except BaseException as exc:
                future.set_exception(exc)

        self.enqueue(_wrapper)
        return future

    def _queue_depth(self) -> int:
        with self._lock:
            return len(self._tasks)

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=_WAKE_POLL_SEC)
            self._wake.clear()

            with self._lock:
                pending, self._tasks = self._tasks, []

            for task in pending:
                if self._stop.is_set():
                    break
                task()
