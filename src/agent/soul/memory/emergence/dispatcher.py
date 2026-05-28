from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor


class EmergenceQueryDispatcher:
    """并发执行 emergence 单点检索，与写入队列分离。"""

    def __init__(self, *, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="memory-emergence",
        )

    def submit(self, fn: Callable[[], None]) -> None:
        self._executor.submit(fn)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
