from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from config.soul.config import SoulConfig
from agent.soul.heartbeat.checklist import ChecklistRegistry, default_checklist
from agent.soul.heartbeat.config import SoulHeartbeatConfig
from agent.soul.heartbeat.console_log import configure_console_log, hb_debug
from agent.soul.heartbeat.orchestrator import HeartbeatOrchestrator

_MEMORY_SLEEP_ITEM_ID = "memory-sleep"
from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult
from agent.soul.heartbeat.worker import SoulEvolutionWorker

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
            checklist=ChecklistRegistry(default_checklist(self._soul_config)),
            soul_config=self._soul_config,
        )
        self._evolution_worker = SoulEvolutionWorker(self._orchestrator)
        self._orchestrator.set_worker(self._evolution_worker)

        self._lock = threading.Lock()

    def tick(self) -> HeartbeatTickResult:
        t0 = time.monotonic()

        with self._lock:
            self._force_tick = False

        in_active = self._in_active_hours()
        if self._soul is not None and self._soul.is_running:
            self._orchestrator.run_due_item(_MEMORY_SLEEP_ITEM_ID)
            if not in_active:
                if self._soul.presence.is_awake():
                    self._soul.run_presence_sleep()
            elif not self._soul.presence.is_awake():
                self._soul.run_presence_wake()

        if not in_active:
            result = HeartbeatTickResult(outcome="skip", reason="outside active hours (sleeping)")
            self._tick_log.append(result)
            hb_debug(logger, "[Heartbeat] skip — outside active hours (sleeping)")
            return result

        if self._soul is None or not self._soul.is_running:
            result = HeartbeatTickResult(outcome="skip", reason="soul not running")
            self._tick_log.append(result)
            hb_debug(logger, "[Heartbeat] skip — soul not running")
            return result

        results = self._orchestrator.run_due(
            exclude_item_ids=frozenset({_MEMORY_SLEEP_ITEM_ID}),
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
        hb_debug(logger, "[Heartbeat] ok — %s (%dms)", reason or "idle", duration_ms)
        return result

    def apply_console_log_config(self) -> None:
        configure_console_log(self._cfg.console_log_enabled)

    def set_soul_service(self, soul: SoulService | None) -> None:
        self._soul = soul
        self._orchestrator.set_soul_service(soul)
        if soul is not None:
            self._soul_config = soul.config
            if soul.is_running:
                self.start_evolution_worker()

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
