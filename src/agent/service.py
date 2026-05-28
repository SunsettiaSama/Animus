"""agent/service.py — AgentService：将 agent 作为持久化服务运行。

职责
----
AgentService 将以下组件组装成一个 start()/stop() 生命周期单元：

    TaskRunner       — 执行调度任务（实现 TaskExecutorProtocol）
    SchedulerEngine  — 顶层调度门面，内含 TemporalClock（独立 daemon 线程）
    SubAgentRunner   — 提供 run_once() 接口，供外部发起临时指令

Soul 心跳（HeartbeatModule / HeartbeatCoreService）由 SoulService 独立持有与驱动，
不经过 SchedulerEngine。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.scheduler.engine import SchedulerEngine
    from runtime.scheduler.config import SchedulerConfig
    from runtime.scheduler.task import ScheduledTask
    from agent.soul.heartbeat.task_runner import TaskRunner

logger = logging.getLogger(__name__)


@dataclass
class AgentServiceConfig:
    """AgentService 的顶层配置入口。"""
    llm_cfg_path: str = "config/llm_core/config.yaml"
    scheduler: "SchedulerConfig | None" = field(default=None)


class AgentService:
    """Agent 作为持久化服务运行（Scheduler 与 Soul 心跳解耦）。"""

    def __init__(
        self,
        llm_cfg_path: str = "config/llm_core/config.yaml",
        scheduler_cfg: "SchedulerConfig | None" = None,
        llm_service: Any = None,
        notify_fn: "Callable[[ScheduledTask, str], None] | None" = None,
        long_term: Any = None,
        timeline: Any = None,
        journal: Any = None,
        channel_router: Any = None,
        life_manager: Any = None,
        persona_manager: Any = None,
        memory_service: Any = None,
        soul_service: Any = None,
    ) -> None:
        from agent.soul.heartbeat.profiles import make_default_scheduler_config
        from agent.soul.heartbeat.task_runner import TaskRunner

        self._llm_cfg_path = llm_cfg_path
        self._llm_service = llm_service
        self._state = "idle"

        if scheduler_cfg is None:
            scheduler_cfg = make_default_scheduler_config(llm_cfg_path=llm_cfg_path)
        self._scheduler_cfg = scheduler_cfg

        self._task_runner: TaskRunner = TaskRunner(
            cfg=scheduler_cfg,
            long_term=long_term,
            timeline=timeline,
            notify_fn=notify_fn,
            engine=None,
            journal=journal,
            channel_router=channel_router,
        )

        self._soul_service = soul_service
        self._persona_manager = persona_manager
        self._memory_service = memory_service
        self._engine: "SchedulerEngine | None" = None

        logger.info(
            "[AgentService] initialized — scheduler_dir=%s",
            scheduler_cfg.scheduler_dir,
        )

    def start(self) -> None:
        if self._state != "idle":
            logger.warning("[AgentService] start() called in state %r, ignored", self._state)
            return

        from runtime.scheduler.engine import SchedulerEngine

        self._engine = SchedulerEngine(
            cfg=self._scheduler_cfg,
            executor=self._task_runner,
            heartbeat=None,
        )
        self._task_runner._engine = self._engine
        self._engine.start()

        if self._soul_service is not None:
            if not self._soul_service.is_running:
                self._soul_service.start()
            self._soul_service.bind_scheduler_engine(self._engine)

        self._state = "running"
        logger.info("[AgentService] started — TemporalClock running (no scheduler→soul heartbeat wire)")

    def stop(self, timeout: float = 10.0) -> None:
        if self._state != "running":
            logger.warning("[AgentService] stop() called in state %r, ignored", self._state)
            return

        assert self._engine is not None
        if self._soul_service is not None and self._soul_service.is_running:
            self._soul_service.stop()
        self._engine.stop()
        self._state = "stopped"
        logger.info("[AgentService] stopped")

    def __enter__(self) -> "AgentService":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == "running"

    def status(self) -> dict:
        engine_status: dict = {}
        if self._engine is not None:
            engine_status = {
                "clock_running": self._engine.is_clock_running,
                "clock_paused": self._engine.is_clock_paused,
                "pending_tasks": len([
                    t for t in self._engine.list_timeline()
                    if getattr(t, "status", None) is not None
                    and str(getattr(t.status, "value", t.status)) == "pending"
                ]),
            }
        soul_hb: list = []
        if self._soul_service is not None and self._soul_service.heartbeat is not None:
            soul_hb = self._soul_service.heartbeat.recent_log(5)
        return {
            "state": self._state,
            "scheduler_dir": self._scheduler_cfg.scheduler_dir,
            "engine": engine_status,
            "soul_heartbeat_recent": soul_hb,
        }

    def run_once(
        self,
        instruction: str,
        profile_name: str = "minimal",
        notify_fn: "Callable[[str, str], None] | None" = None,
    ) -> dict:
        from agent.runner import SubAgentRunner
        from agent.profile import SubAgentProfile

        profile: SubAgentProfile = (
            self._scheduler_cfg.profiles.get(profile_name)
            or self._scheduler_cfg.profiles.get("minimal")
            or SubAgentProfile()
        )
        return SubAgentRunner().run_sync(
            instruction=instruction,
            profile=profile,
            llm_cfg_path=self._llm_cfg_path,
            scheduler_engine=self._engine,
            notify_fn=notify_fn,
            soul=self._soul_service,
        )

    def force_heartbeat(self):
        """触发 Soul 心跳 tick（需 Soul 已运行）。"""
        if self._soul_service is None or not self._soul_service.is_running:
            raise RuntimeError("Soul 未运行，无法触发心跳")
        return self._soul_service.force_heartbeat_tick()

    def set_soul_service(self, soul: Any) -> None:
        self._soul_service = soul
        if self._engine is not None:
            soul.bind_scheduler_engine(self._engine)
        if self._state == "running" and not soul.is_running:
            soul.start()

    @property
    def engine(self) -> "SchedulerEngine | None":
        return self._engine

    @property
    def task_runner(self) -> "TaskRunner":
        return self._task_runner
