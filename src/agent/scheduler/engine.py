from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from agent.scheduler.config import SchedulerConfig
from agent.scheduler.runner import TaskRunner
from agent.scheduler.store import TaskStore
from agent.scheduler.task import ScheduledTask, TaskStatus, Trigger


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchedulerEngine:
    def __init__(
        self,
        cfg: SchedulerConfig,
        long_term=None,
        timeline=None,
    ):
        self._cfg    = cfg
        self._store  = TaskStore(cfg.scheduler_dir)
        self._runner = TaskRunner(cfg, long_term=long_term, timeline=timeline)

    # ── Scheduling API ────────────────────────────────────────────────────────

    def schedule_once(
        self,
        name: str,
        instruction: str,
        at: datetime,
        profile: str = "minimal",
    ) -> ScheduledTask:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            name=name,
            instruction=instruction,
            trigger=Trigger(type="once", at=at.isoformat()),
            config_profile=profile,
            status=TaskStatus.pending,
            created_at=_utcnow_iso(),
            next_run_at=at.isoformat(),
        )
        self._store.add(task)
        return task

    def schedule_interval(
        self,
        name: str,
        instruction: str,
        seconds: int,
        profile: str = "minimal",
        start_at: datetime | None = None,
    ) -> ScheduledTask:
        first_run = start_at or datetime.now(timezone.utc)
        if first_run.tzinfo is None:
            first_run = first_run.replace(tzinfo=timezone.utc)
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            name=name,
            instruction=instruction,
            trigger=Trigger(type="interval", interval_seconds=seconds),
            config_profile=profile,
            status=TaskStatus.pending,
            created_at=_utcnow_iso(),
            next_run_at=first_run.isoformat(),
        )
        self._store.add(task)
        return task

    def cancel(self, task_id: str) -> bool:
        return self._store.cancel(task_id)

    def list_timeline(self) -> list[ScheduledTask]:
        return self._store.list_all()

    def get(self, task_id: str) -> ScheduledTask | None:
        return self._store.get(task_id)

    # ── Async polling loop ────────────────────────────────────────────────────

    async def start(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            for task in self._store.get_due_tasks(now):
                asyncio.create_task(self._runner.run(task, self._store))
            await asyncio.sleep(self._cfg.poll_interval)

    def start_background(self) -> asyncio.Task:
        return asyncio.create_task(self.start())
