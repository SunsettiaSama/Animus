from __future__ import annotations

import threading
from concurrent.futures import Future
from typing import Callable

from infra.threading import ThreadLease, get_thread_registry

_WAKE_POLL_SEC = 0.5


def _owner_from_name(name: str) -> str:
    head = name.strip().split("-", 1)[0]
    return head or "domain"


class DomainWorker:
    """单域 FIFO 队列 + 单消费线程。写路径统一经 enqueue / submit。

    线程本体向 ``infra.threading`` 申请租约；队列与协作停止仍由本类负责。
    """

    def __init__(self, name: str, *, owner: str | None = None) -> None:
        self._name = name
        self._owner = (owner or _owner_from_name(name)).strip()
        self._tasks: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._lease: ThreadLease | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def owner(self) -> str:
        return self._owner

    def start(self) -> None:
        if self._lease is not None and self._lease.is_alive():
            return
        self._stop.clear()
        lease = get_thread_registry().request(
            self._owner,
            self._name,
            self._run,
            daemon=True,
            stop=self._signal_stop,
        )
        lease.start()
        self._lease = lease

    def stop(self) -> None:
        self._signal_stop()
        if self._lease is not None:
            self._lease.stop(timeout=30.0)
            self._lease = None

    def status(self) -> dict:
        alive = self._lease is not None and self._lease.is_alive()
        with self._lock:
            queued = len(self._tasks)
        return {
            "state": "running" if alive else "stopped",
            "queued": queued,
            "owner": self._owner,
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

    def _signal_stop(self) -> None:
        self._stop.set()
        self._wake.set()

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
