from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ..schedule import ChecklistItem
from ..console_log import hb_info

if TYPE_CHECKING:
    from .orchestrator import HeartbeatOrchestrator

logger = logging.getLogger(__name__)

_WAKE_POLL_SEC = 0.5


class SoulEvolutionWorker:
    """Soul 演化后台 worker：heartbeat 只入队，重任务在此线程执行。"""

    def __init__(self, orchestrator: HeartbeatOrchestrator) -> None:
        self._orchestrator = orchestrator
        self._tasks: list[ChecklistItem] = []
        self._pending_ids: set[str] = set()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        t = threading.Thread(target=self._run, name="soul-evolution", daemon=True)
        t.start()
        self._thread = t
        hb_info(logger, "[SoulEvolutionWorker] started")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=30.0)
            if self._thread.is_alive():
                logger.warning(
                    "[SoulEvolutionWorker] 线程未在 30s 内退出（可能被长调用阻塞），"
                    "将以 daemon 线程随进程退出",
                )
            self._thread = None
        with self._lock:
            self._tasks.clear()
            self._pending_ids.clear()
        hb_info(logger, "[SoulEvolutionWorker] stopped")

    def status(self) -> dict:
        with self._lock:
            queued = len(self._tasks)
            pending = list(self._pending_ids)
        alive = self._thread is not None and self._thread.is_alive()
        return {
            "state": "running" if alive else "stopped",
            "queued": queued,
            "pending_item_ids": pending,
        }

    def enqueue(self, item: ChecklistItem) -> bool:
        """入队演化任务；同一 checklist id 在 pending 期间不重复入队。"""
        with self._lock:
            if item.id in self._pending_ids:
                return False
            self._pending_ids.add(item.id)
            self._tasks.append(item)
        self._wake.set()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=_WAKE_POLL_SEC)
            self._wake.clear()

            with self._lock:
                pending, self._tasks = self._tasks, []

            for item in pending:
                self._run_one(item)

    def _run_one(self, item: ChecklistItem) -> None:
        hb_info(
            logger,
            "[SoulEvolutionWorker] execute %s/%s",
            item.domain,
            item.action,
        )
        try:
            result = self._orchestrator.execute_item(item)
        except Exception:  # noqa: BLE001 — 演化 worker 是唤起线的一部分，不允许线程死亡
            logger.exception(
                "[SoulEvolutionWorker] execute %s/%s 抛异常（跳过该项，继续）",
                item.domain,
                item.action,
            )
            result = None
        else:
            hb_info(
                logger,
                "[SoulEvolutionWorker] done %s/%s ok=%s",
                item.domain,
                item.action,
                result.ok,
            )
        finally:
            # 异常路径同样释放 pending：否则该项永久滞留，再也无法入队
            with self._lock:
                self._pending_ids.discard(item.id)
