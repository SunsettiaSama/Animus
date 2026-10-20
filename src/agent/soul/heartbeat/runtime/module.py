from __future__ import annotations

import logging
import threading
import time
from typing import TYPE_CHECKING

from config.soul.config import SoulConfig
from agent.soul.heartbeat.schedule import ChecklistRegistry
from agent.soul.heartbeat.config import SoulHeartbeatConfig
from agent.soul.heartbeat.console_log import configure_console_log, hb_debug
from agent.soul.heartbeat.orchestrate.orchestrator import HeartbeatOrchestrator
from agent.soul.heartbeat.policy import may_sleep
from agent.soul.heartbeat.vitals import VitalsBuilder
from agent.soul.heartbeat.vitals.snapshot import SoulVitals
from agent.soul.heartbeat.window import within_window

from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
from agent.soul.heartbeat.orchestrate.worker import SoulEvolutionWorker

if TYPE_CHECKING:
    from agent.soul.service import SoulService

logger = logging.getLogger(__name__)


class HeartbeatModule:
    """Soul 心跳模块：独立时间线，由 SoulService + HeartbeatCoreService 驱动。"""

    def __init__(
        self,
        cfg: SoulHeartbeatConfig,
        log_dir: str,
        llm_cfg_path: str,
        soul_config: SoulConfig | None = None,
    ) -> None:
        self._cfg = cfg
        configure_console_log(cfg.console_log_enabled)
        self._soul_config = soul_config or SoulConfig.load_default()
        self._log_dir = log_dir
        self._llm_cfg_path = llm_cfg_path
        self._tick_log = HeartbeatTickLog(log_dir)
        self._force_tick: bool = False
        self._soul: SoulService | None = None

        self._orchestrator = HeartbeatOrchestrator(
            checklist=ChecklistRegistry(),
            soul_config=self._soul_config,
        )
        self._evolution_worker = SoulEvolutionWorker(self._orchestrator)
        self._orchestrator.set_worker(self._evolution_worker)
        self._orchestrator.set_vitals_provider(lambda: self.vitals())

        self._vitals_builder = VitalsBuilder.default(
            soul=None, worker=self._evolution_worker, core=None
        )
        self._core_service = None  # attach_core_service 回填

        self._lock = threading.Lock()

    def tick(self) -> HeartbeatTickResult:
        t0 = time.monotonic()

        with self._lock:
            self._force_tick = False

        in_active = self._in_active_hours()
        if self._soul is not None and self._soul.is_running:
            # 活跃时段外仍需执行的项（如 memory-sleep 的夜间整理）先行
            for off_item in self._orchestrator.checklist.off_hours_items():
                if off_item.enabled:
                    self._orchestrator.run_due_item(off_item.id)
            if not in_active:
                if self._soul.presence.is_awake():
                    ok, reason = may_sleep(self.vitals())
                    if ok:
                        self._soul.run_presence_sleep()
                    else:
                        hb_debug(logger, "[Heartbeat] sleep deferred - %s", reason)
            elif not self._soul.presence.is_awake():
                self._soul.run_presence_wake()

        if not in_active:
            result = HeartbeatTickResult(outcome="skip", reason="outside active hours (sleeping)")
            self._tick_log.append(result)
            hb_debug(logger, "[Heartbeat] skip - outside active hours (sleeping)")
            return result

        if self._soul is None or not self._soul.is_running:
            result = HeartbeatTickResult(outcome="skip", reason="soul not running")
            self._tick_log.append(result)
            hb_debug(logger, "[Heartbeat] skip - soul not running")
            return result

        results = self._orchestrator.run_due(
            exclude_item_ids=frozenset(i.id for i in self._orchestrator.checklist.off_hours_items()),
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        ran = sum(1 for r in results if r.ok)
        enqueued = sum(1 for r in results if r.async_enqueued)
        parts: list[str] = []
        if ran:
            parts.append(f"ran {ran}/{len(results)}")
        if enqueued:
            parts.append(f"enqueued {enqueued}")
        reason = " ".join(parts)
        result = HeartbeatTickResult(outcome="ok", reason=reason, duration_ms=duration_ms)
        self._tick_log.append(result)
        hb_debug(logger, "[Heartbeat] ok - %s (%dms)", reason or "idle", duration_ms)
        return result

    def apply_console_log_config(self) -> None:
        configure_console_log(self._cfg.console_log_enabled)

    def set_soul_service(self, soul: SoulService | None) -> None:
        self._soul = soul
        self._orchestrator.set_soul_service(soul)
        # 体征探针随 soul 接线重建；core 引用保留（由 attach_core_service 维护）
        self._vitals_builder = VitalsBuilder.default(
            soul=soul, worker=self._evolution_worker, core=self._core_service
        )
        if soul is not None:
            self._soul_config = soul.config
            if soul.is_running:
                self.start_evolution_worker()

    def attach_core_service(self, core) -> None:
        """core 线程由 SoulService 在 start 后创建，此处回填自身探针。"""
        from agent.soul.heartbeat.probe import HeartbeatSelfProbe

        self._core_service = core
        self._vitals_builder.register(HeartbeatSelfProbe(core))

    def vitals(self) -> SoulVitals:
        """当前生命体征快照（探针容错，绝不抛）。"""
        return self._vitals_builder.snapshot()

    def set_scheduler_engine(self, engine) -> None:
        self._orchestrator.set_scheduler_engine(engine)

    def start_evolution_worker(self) -> None:
        self._evolution_worker.start()

    def stop_evolution_worker(self) -> None:
        self._evolution_worker.stop()

    @property
    def config(self) -> SoulHeartbeatConfig:
        return self._cfg

    @property
    def orchestrator(self) -> HeartbeatOrchestrator:
        return self._orchestrator

    @property
    def evolution_worker(self) -> SoulEvolutionWorker:
        return self._evolution_worker

    @property
    def pending_force(self) -> bool:
        with self._lock:
            return self._force_tick

    def force_tick(self) -> None:
        with self._lock:
            self._force_tick = True

    def recent_log(self, n: int = 50) -> list[dict]:
        return self._tick_log.recent(n)

    def _in_active_hours(self) -> bool:
        return within_window(
            self._cfg.active_hours_start,
            self._cfg.active_hours_end,
            self._cfg.active_timezone,
        )
