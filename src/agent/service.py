"""agent/service.py — AgentService：将 agent 作为持久化服务运行。

职责
----
AgentService 将以下四个组件组装成一个 start()/stop() 生命周期单元：

    HeartbeatModule  — 定期读取 HEARTBEAT.md，通过 LLM precheck 决定是否需要
                       主动介入（escalate → SubAgentRunner）
    TaskRunner       — 执行调度任务（实现 TaskExecutorProtocol）
    SchedulerEngine  — 顶层调度门面，内含 TemporalClock（独立 daemon 线程）；
                       时钟驱动任务分发 + 心跳 tick
    SubAgentRunner   — 提供 run_once() 接口，供外部发起临时指令

组装逻辑
--------
    AgentService.__init__()
        ├─ 构建 SchedulerConfig（含 profiles）
        ├─ 创建 TaskRunner（此时 engine=None，start() 后补 wire）
        └─ 创建 HeartbeatModule（此时 scheduler_engine=None，start() 后补 wire）

    AgentService.start()
        ├─ 创建 SchedulerEngine（传入 task_runner + heartbeat）
        ├─ 回注 engine 到 heartbeat._checker 和 task_runner._engine
        └─ engine.start() → TemporalClock.start()

状态机：idle → running → stopped
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.scheduler.engine import SchedulerEngine
    from runtime.scheduler.config import SchedulerConfig
    from runtime.scheduler.task import ScheduledTask
    from agent.soul.heartbeat.module import HeartbeatModule
    from agent.soul.heartbeat.task_runner import TaskRunner
    from agent.soul.heartbeat.tick_log import HeartbeatTickResult

logger = logging.getLogger(__name__)


@dataclass
class AgentServiceConfig:
    """AgentService 的顶层配置入口。

    scheduler  包含 heartbeat 子配置（HeartbeatConfig 作为 SchedulerConfig.heartbeat
               字段存在），无需单独传入 HeartbeatConfig。
    """
    llm_cfg_path: str = "config/llm_core/config.yaml"
    scheduler: "SchedulerConfig | None" = field(default=None)


class AgentService:
    """Agent 作为持久化服务运行。

    用法
    ----
    ::

        svc = AgentService(
            llm_cfg_path="config/llm_core/config.yaml",
        )
        svc.start()                          # 启动 TemporalClock 后台线程
        svc.force_heartbeat()               # 立即触发一次心跳检查
        result = svc.run_once("帮我搜索…")  # 临时指令（在调用线程中同步执行）
        svc.stop()                           # 停止时钟

    参数
    ----
    llm_cfg_path:
        LLM YAML 配置路径；传入 scheduler_cfg 时仍可独立指定（优先用于 run_once）。
    scheduler_cfg:
        完整 SchedulerConfig；None 时使用 make_default_scheduler_config 生成默认配置。
    llm_service:
        可选，提供 get_aux_llm(name) 接口（如 AppLLMService）；
        HeartbeatChecker precheck 时优先从此处取 auxiliary LLM。
    notify_fn:
        调度任务完成后的通知回调 (task, answer) -> None。
    long_term:
        长期记忆实例，供 TaskRunner 写入任务结果摘要。
    timeline:
        时间线实例，供 TaskRunner 追加事件。
    journal:
        WorkJournal 实例，供 TaskRunner / HeartbeatChecker 写入运行日志。
    channel_router:
        ChannelRouter 实例，供主动通知投递到对话频道。
    life_manager:
        可选的 LifeManager，供 HeartbeatModule._run_life_hooks 调用。
    persona_manager:
        可选的 PersonaManager；用于日终回顾取静态画像，并向 HeartbeatCoreService 注册 wander 漂移端口。
    memory_service:
        可选的 MemoryService；向 HeartbeatCoreService 注册记忆 wander.tick 端口。
    """

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
    ) -> None:
        from agent.soul.heartbeat.profiles import make_default_scheduler_config
        from agent.soul.heartbeat.module import HeartbeatModule
        from agent.soul.heartbeat.task_runner import TaskRunner

        self._llm_cfg_path = llm_cfg_path
        self._llm_service = llm_service
        self._state = "idle"

        # ── 1. SchedulerConfig ───────────────────────────────────────────────
        if scheduler_cfg is None:
            scheduler_cfg = make_default_scheduler_config(llm_cfg_path=llm_cfg_path)
        self._scheduler_cfg = scheduler_cfg

        # ── 2. TaskRunner（实现 TaskExecutorProtocol）──────────────────────
        self._task_runner: TaskRunner = TaskRunner(
            cfg=scheduler_cfg,
            long_term=long_term,
            timeline=timeline,
            notify_fn=notify_fn,
            engine=None,          # start() 后补 wire
            journal=journal,
            channel_router=channel_router,
        )

        # ── 3. HeartbeatModule（实现 HeartbeatProtocol）────────────────────
        self._heartbeat: HeartbeatModule = HeartbeatModule(
            cfg=scheduler_cfg.heartbeat,
            scheduler_dir=scheduler_cfg.scheduler_dir,
            llm_service=llm_service,
            llm_cfg_path=llm_cfg_path,
            scheduler_engine=None,  # start() 后补 wire
            scheduler_cfg=scheduler_cfg,
            journal=journal,
            channel_router=channel_router,
        )
        if life_manager is not None:
            self._heartbeat.set_life_manager(life_manager)

        self._persona_manager = persona_manager
        self._memory_service = memory_service
        if persona_manager is not None:
            self._heartbeat.set_persona_manager(persona_manager)

        self._engine: "SchedulerEngine | None" = None
        self._core_heartbeat: Any = None

        logger.info(
            "[AgentService] initialized — scheduler_dir=%s  heartbeat_interval=%ds",
            scheduler_cfg.scheduler_dir,
            scheduler_cfg.heartbeat.interval,
        )

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """启动服务：创建 SchedulerEngine、补 wire engine 引用、启动 TemporalClock。"""
        if self._state != "idle":
            logger.warning("[AgentService] start() called in state %r, ignored", self._state)
            return

        if self._scheduler_cfg.heartbeat.core_service_enabled:
            self._scheduler_cfg.heartbeat.clock_drives_heartbeat = False
            logger.info(
                "[AgentService] core heartbeat thread enabled — TemporalClock heartbeat ticks disabled"
            )

        from runtime.scheduler.engine import SchedulerEngine

        self._engine = SchedulerEngine(
            cfg=self._scheduler_cfg,
            executor=self._task_runner,
            heartbeat=self._heartbeat,
        )

        # 补 wire：HeartbeatChecker 和 TaskRunner 都需要 engine 引用
        self._heartbeat._checker._scheduler_engine = self._engine
        self._task_runner._engine = self._engine

        self._engine.start()
        if self._scheduler_cfg.heartbeat.core_service_enabled:
            from agent.soul.heartbeat.core_service import HeartbeatCoreService

            self._core_heartbeat = HeartbeatCoreService(
                heartbeat=self._heartbeat,
                llm_service=self._llm_service,
                llm_cfg_path=self._llm_cfg_path,
            )
            if self._memory_service is not None:
                self._core_heartbeat.set_memory_port(self._memory_service)
            if self._persona_manager is not None:
                self._core_heartbeat.set_persona_port(self._persona_manager)
            if self._heartbeat._life_manager is not None:
                self._core_heartbeat.set_life_port(self._heartbeat._life_manager)
            self._core_heartbeat.start()

        self._state = "running"
        logger.info("[AgentService] started — TemporalClock running")

    def stop(self, timeout: float = 10.0) -> None:
        """停止服务：停止 TemporalClock，等待后台线程退出。"""
        if self._state != "running":
            logger.warning("[AgentService] stop() called in state %r, ignored", self._state)
            return

        assert self._engine is not None
        if self._core_heartbeat is not None:
            self._core_heartbeat.stop()
            self._core_heartbeat = None
        self._engine.stop()
        self._state = "stopped"
        logger.info("[AgentService] stopped")

    def __enter__(self) -> "AgentService":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.stop()

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        """idle | running | stopped"""
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == "running"

    def status(self) -> dict:
        """返回服务当前状态快照，可直接序列化为 JSON 用于健康检查。"""
        engine_status: dict = {}
        if self._engine is not None:
            engine_status = {
                "clock_running": self._engine.is_clock_running,
                "clock_paused":  self._engine.is_clock_paused,
                "pending_tasks": len([
                    t for t in self._engine.list_timeline()
                    if getattr(t, "status", None) is not None
                    and str(getattr(t.status, "value", t.status)) == "pending"
                ]),
            }
        return {
            "state":             self._state,
            "scheduler_dir":     self._scheduler_cfg.scheduler_dir,
            "heartbeat_interval": self._scheduler_cfg.heartbeat.interval,
            "engine":            engine_status,
            "heartbeat_recent":  self._heartbeat.recent_log(5),
        }

    # ── 操作接口 ──────────────────────────────────────────────────────────────

    def run_once(
        self,
        instruction: str,
        profile_name: str = "minimal",
        notify_fn: "Callable[[str, str], None] | None" = None,
    ) -> dict:
        """在调用线程中同步执行一次临时指令，返回 {"answer": ..., "step_count": ..., "steps_log": [...]}。

        不经过调度器，直接使用 SubAgentRunner，适合交互式查询。
        scheduler_engine 引用自动传入，agent 可在执行中使用调度工具。
        """
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
        )

    def force_heartbeat(self) -> "HeartbeatTickResult":
        """立即执行一次心跳检查（同步，在调用线程运行）。"""
        return self._heartbeat.tick()

    def update_heartbeat_file(self, content: str) -> None:
        """覆盖 HEARTBEAT.md 内容，下次 tick 时生效。"""
        self._heartbeat.write_file(content)

    def read_heartbeat_file(self) -> str:
        """读取当前 HEARTBEAT.md 内容。"""
        return self._heartbeat.read_file()

    # ── 调度器代理（便捷接口）─────────────────────────────────────────────────

    @property
    def engine(self) -> "SchedulerEngine | None":
        """返回底层 SchedulerEngine；start() 之前为 None。"""
        return self._engine

    @property
    def heartbeat(self) -> "HeartbeatModule":
        return self._heartbeat

    @property
    def task_runner(self) -> "TaskRunner":
        return self._task_runner
