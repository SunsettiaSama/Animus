from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor, Future
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.flow.document import PlanDocument

logger = logging.getLogger(__name__)


class PlanExecutionContext:
    """
    Owns all ThreadPoolExecutor resources for one plan run.

    Lifecycle: created before orchestrator.run(), shut down in its finally block.
    All four pools are named with the plan_id prefix for easy log tracing.

    Thread budget:
    - planner_pool     max_workers=2  (PlannerAgent LLM calls)
    - replanner_pool   max_workers=2  (ReplannerAgent LLM calls)
    - worker_pool      max_workers=effective_width  (SubAgent TaoLoops)
    - semaphore        asyncio.Semaphore(effective_width)  mirrors worker_pool slots

    effective_width is determined by:
      1. parallel_limit > 0 in OrchestratorConfig → use that value
      2. parallel_limit == 0 → compute_dag_width() of the initial doc
    """

    def __init__(self, plan_id: str, effective_width: int) -> None:
        self._plan_id = plan_id
        self._effective_width = effective_width
        prefix = plan_id[:8]

        self.planner_pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix=f"plan-{prefix}-planner",
        )
        self.replanner_pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix=f"plan-{prefix}-replanner",
        )
        self.worker_pool = ThreadPoolExecutor(
            max_workers=max(effective_width, 1),
            thread_name_prefix=f"plan-{prefix}-worker",
        )
        self.semaphore = asyncio.Semaphore(max(effective_width, 1))

    @classmethod
    def from_config(cls, plan_id: str, parallel_limit: int, doc: "PlanDocument") -> "PlanExecutionContext":
        if parallel_limit > 0:
            width = parallel_limit
        else:
            width = doc.compute_dag_width()
        logger.info(
            "[PlanExecutionContext] plan=%s effective_width=%d (parallel_limit=%d dag_width=%d)",
            plan_id[:8], width, parallel_limit, doc.compute_dag_width(),
        )
        return cls(plan_id=plan_id, effective_width=width)

    def resize_semaphore(self, new_width: int) -> None:
        """Replace the asyncio semaphore after a replan changes DAG width.

        Safe to call only when no coroutines are currently waiting on the semaphore
        (i.e. between task waves, not mid-execution).
        """
        self._effective_width = new_width
        self.semaphore = asyncio.Semaphore(max(new_width, 1))
        new_workers = max(new_width, 1)
        if new_workers > self.worker_pool._max_workers:  # type: ignore[attr-defined]
            self.worker_pool._max_workers = new_workers  # type: ignore[attr-defined]
            logger.info("[PlanExecutionContext] semaphore resized to %d", new_width)

    def shutdown(self, wait: bool = True, timeout: float = 30.0) -> None:
        """Shut down all thread pools in order, with a per-pool timeout."""
        for name, pool in (
            ("worker", self.worker_pool),
            ("planner", self.planner_pool),
            ("replanner", self.replanner_pool),
        ):
            pool.shutdown(wait=wait, cancel_futures=not wait)
            logger.debug("[PlanExecutionContext] %s pool shut down", name)
