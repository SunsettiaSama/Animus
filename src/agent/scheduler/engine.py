from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from agent.scheduler.clock import TemporalClock
from agent.scheduler.config import SchedulerConfig
from agent.scheduler.heartbeat import HeartbeatModule
from agent.scheduler.runner import TaskRunner
from agent.scheduler.store import TaskStore
from agent.scheduler.task import DeliveryMode, ScheduledTask, TaskStatus, Trigger

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SchedulerEngine:
    """Top-level scheduler facade.

    Internally uses a :class:`TemporalClock` running on a dedicated daemon
    thread — completely isolated from the uvicorn asyncio event loop.
    """

    def __init__(
        self,
        cfg: SchedulerConfig,
        long_term=None,
        timeline=None,
        notify_fn: Callable[[ScheduledTask, str], None] | None = None,
        journal=None,
        channel_router=None,
        llm_service=None,
    ):
        self._cfg = cfg
        self._store = TaskStore(cfg.scheduler_dir)
        self._runner = TaskRunner(
            cfg,
            long_term=long_term,
            timeline=timeline,
            notify_fn=notify_fn,
            engine=self,
            journal=journal,
            channel_router=channel_router,
        )
        self._heartbeat = HeartbeatModule(
            cfg=cfg.heartbeat,
            scheduler_dir=cfg.scheduler_dir,
            llm_service=llm_service,
            llm_cfg_path=cfg.llm_cfg_path,
            scheduler_engine=self,
            scheduler_cfg=cfg,
            journal=journal,
            channel_router=channel_router,
        )
        self._clock = TemporalClock(cfg, self._store, self._runner,
                                    heartbeat_module=self._heartbeat)

    def set_notify_fn(self, fn: Callable[[ScheduledTask, str], None]) -> None:
        self._runner._notify_fn = fn

    @property
    def heartbeat(self) -> HeartbeatModule:
        return self._heartbeat

    def trigger_proactive_now(self) -> None:
        """Immediately signal the clock to run a heartbeat tick on the next iteration."""
        self._heartbeat.force_tick()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the clock thread (synchronous, non-blocking)."""
        self._clock.start()

    def stop(self) -> None:
        self._clock.stop()

    def pause_clock(self) -> None:
        """Pause the clock tick loop without stopping the thread."""
        self._clock.pause()

    def resume_clock(self) -> None:
        """Resume the clock tick loop after a pause."""
        self._clock.resume()

    @property
    def is_clock_running(self) -> bool:
        return self._clock.is_running

    @property
    def is_clock_paused(self) -> bool:
        return self._clock.is_paused

    # ── Scheduling API ────────────────────────────────────────────────────────

    def schedule_once(
        self,
        name: str,
        instruction: str,
        at: datetime,
        profile: str = "minimal",
        reply_target: dict | None = None,
        delivery: DeliveryMode | str = DeliveryMode.push,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        on_complete: str | None = None,
        context: dict | None = None,
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
            reply_target=reply_target,
            delivery=DeliveryMode(delivery),
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            on_complete=on_complete,
            context=context,
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
        reply_target: dict | None = None,
        delivery: DeliveryMode | str = DeliveryMode.push,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        on_complete: str | None = None,
        context: dict | None = None,
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
            reply_target=reply_target,
            delivery=DeliveryMode(delivery),
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            on_complete=on_complete,
            context=context,
        )
        self._store.add(task)
        return task

    def schedule_cron(
        self,
        name: str,
        instruction: str,
        cron_expr: str,
        profile: str = "minimal",
        reply_target: dict | None = None,
        delivery: DeliveryMode | str = DeliveryMode.push,
        max_retries: int = 0,
        retry_delay_seconds: int = 60,
        on_complete: str | None = None,
        context: dict | None = None,
    ) -> ScheduledTask:
        from agent.scheduler.store import _next_cron
        first_run = _next_cron(cron_expr, datetime.now(timezone.utc))
        if first_run is None:
            raise ValueError(f"Invalid cron expression: {cron_expr!r}")
        task = ScheduledTask(
            id=str(uuid.uuid4()),
            name=name,
            instruction=instruction,
            trigger=Trigger(type="cron", cron_expr=cron_expr),
            config_profile=profile,
            status=TaskStatus.pending,
            created_at=_utcnow_iso(),
            next_run_at=first_run.isoformat(),
            reply_target=reply_target,
            delivery=DeliveryMode(delivery),
            max_retries=max_retries,
            retry_delay_seconds=retry_delay_seconds,
            on_complete=on_complete,
            context=context,
        )
        self._store.add(task)
        return task

    def cancel(self, task_id: str) -> bool:
        return self._store.cancel(task_id)

    def pause(self, task_id: str) -> bool:
        return self._store.pause(task_id)

    def resume(self, task_id: str) -> bool:
        return self._store.resume(task_id)

    def list_timeline(self) -> list[ScheduledTask]:
        return self._store.list_all()

    def get(self, task_id: str) -> ScheduledTask | None:
        return self._store.get(task_id)

    # ── Built-in convenience tasks ────────────────────────────────────────────

    def schedule_daily_planner(
        self,
        hour: int = 8,
        reply_target: dict | None = None,
    ) -> ScheduledTask:
        """Register a daily cron task that asks the agent to plan today's schedule."""
        cron_expr = f"0 {hour} * * *"
        name = "__daily_planner__"
        existing = [t for t in self._store.list_all() if t.name == name and t.status != TaskStatus.cancelled]
        if existing:
            return existing[0]
        instruction = (
            "请使用 timeline_read 工具查看今天已有的事件和任务，"
            "然后根据当前记忆和目标，为今天剩余时间制定一个合理的行动计划，"
            "并使用 scheduler_add 工具将具体任务预约到时间轴上。"
        )
        return self.schedule_cron(
            name=name,
            instruction=instruction,
            cron_expr=cron_expr,
            profile="with_memory",
            reply_target=reply_target,
            delivery=DeliveryMode.push,
        )

    def schedule_daily_review(
        self,
        hour: int = 22,
        reply_target: dict | None = None,
    ) -> ScheduledTask:
        """Register a daily cron task that reviews today's timeline and writes to LTM."""
        cron_expr = f"0 {hour} * * *"
        name = "__daily_review__"
        existing = [t for t in self._store.list_all() if t.name == name and t.status != TaskStatus.cancelled]
        if existing:
            return existing[0]
        instruction = (
            "请使用 timeline_read 工具读取今天的所有事件，"
            "总结今天完成了什么、遇到了什么问题、有什么值得记住的经验，"
            "并将这份今日回顾写入长期记忆。"
        )
        return self.schedule_cron(
            name=name,
            instruction=instruction,
            cron_expr=cron_expr,
            profile="with_memory",
            reply_target=reply_target,
            delivery=DeliveryMode.store_only,
        )
