from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from runtime.scheduler.heartbeat_config import HeartbeatConfig
from config.soul.config import SoulConfig
from agent.soul.heartbeat.checklist import ChecklistRegistry, default_checklist
from agent.soul.heartbeat.orchestrator import HeartbeatOrchestrator
from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
from agent.soul.heartbeat.worker import SoulEvolutionWorker

if TYPE_CHECKING:
    from agent.soul.service import SoulService

logger = logging.getLogger(__name__)


class HeartbeatModule:
    """Soul 心跳模块：唯一持有 HeartbeatOrchestrator；tick 触发 checklist，重任务异步演化。"""

    def __init__(
        self,
        cfg: HeartbeatConfig,
        scheduler_dir: str,
        llm_cfg_path: str,
        scheduler_engine=None,
        scheduler_cfg=None,
        soul_config: SoulConfig | None = None,
    ) -> None:
        self._cfg = cfg
        self._soul_config = soul_config or SoulConfig.load_default()
        self._scheduler_dir = scheduler_dir
        self._llm_cfg_path = llm_cfg_path
        self._scheduler_engine = scheduler_engine
        self._scheduler_cfg = scheduler_cfg
        self._tick_log = HeartbeatTickLog(scheduler_dir)
        self._force_tick: bool = False
        self._soul: SoulService | None = None

        self._orchestrator = HeartbeatOrchestrator(
            checklist=ChecklistRegistry(default_checklist(self._soul_config)),
            soul_config=self._soul_config,
        )
        self._evolution_worker = SoulEvolutionWorker(self._orchestrator)
        self._orchestrator.set_worker(self._evolution_worker)
        if scheduler_engine is not None:
            self._orchestrator.set_scheduler_engine(scheduler_engine)

        self._lock = threading.Lock()

    def tick(self) -> HeartbeatTickResult:
        t0 = time.monotonic()

        with self._lock:
            self._force_tick = False

        if not self._in_active_hours():
            result = HeartbeatTickResult(outcome="skip", reason="outside active hours")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — outside active hours")
            return result

        if self._soul is None or not self._soul.is_running:
            result = HeartbeatTickResult(outcome="skip", reason="soul not running")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — soul not running")
            return result

        results = self._orchestrator.run_due()
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
        logger.debug("[Heartbeat] ok — %s (%dms)", reason or "idle", duration_ms)
        return result

    def set_soul_service(self, soul: SoulService | None) -> None:
        self._soul = soul
        self._orchestrator.set_soul_service(soul)
        if soul is not None:
            self._soul_config = soul.config
            soul.bind_heartbeat(self)
            if soul.is_running:
                self.start_evolution_worker()
        if self._scheduler_engine is not None:
            self._orchestrator.set_scheduler_engine(self._scheduler_engine)

    def set_scheduler_engine(self, engine) -> None:
        self._scheduler_engine = engine
        self._orchestrator.set_scheduler_engine(engine)

    def start_evolution_worker(self) -> None:
        self._evolution_worker.start()

    def stop_evolution_worker(self) -> None:
        self._evolution_worker.stop()

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
        start_str = self._cfg.active_hours_start
        end_str = self._cfg.active_hours_end
        tz_name = self._cfg.active_timezone
        if not start_str or not end_str:
            return True
        from datetime import time as dtime
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        now_local = datetime.now(tz).time()
        start = dtime.fromisoformat(start_str)
        end_ = dtime.fromisoformat(end_str)
        return start <= now_local <= end_
