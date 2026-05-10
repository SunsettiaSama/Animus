from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.scheduler.heartbeat.config import HeartbeatConfig
from agent.scheduler.heartbeat.checker import HeartbeatChecker
from agent.scheduler.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT_MD = """\
# Heartbeat Checklist

- 检查时间线，有无 1 小时内到期的任务？如有，酌情提前通知用户。
- 有无 pending 超过 24h 的任务？是否需要重新安排？
- 无事可做时，只回复 HEARTBEAT_OK。
"""


class HeartbeatModule:
    """Self-contained heartbeat subsystem.

    Owned by SchedulerEngine.  TemporalClock calls ``tick()`` periodically
    via ``asyncio.to_thread``.  Does NOT access TaskStore; completely parallel
    to the task-execution path.
    """

    def __init__(
        self,
        cfg: HeartbeatConfig,
        scheduler_dir: str,
        llm_service,        # LLMService | None
        llm_cfg_path: str,
        scheduler_engine,   # SchedulerEngine
        scheduler_cfg,      # SchedulerConfig
        journal=None,
        channel_router=None,
    ) -> None:
        self._cfg = cfg
        self._scheduler_dir = scheduler_dir
        self._tick_log = HeartbeatTickLog(scheduler_dir)
        self._checker = HeartbeatChecker(
            cfg=cfg,
            llm_service=llm_service,
            llm_cfg_path=llm_cfg_path,
            scheduler_engine=scheduler_engine,
            scheduler_cfg=scheduler_cfg,
            journal=journal,
            channel_router=channel_router,
        )
        self._force_tick: bool = False
        self._escalate_count: int = 0
        self._escalate_date: str = ""
        self._lock = threading.Lock()
        self._ensure_heartbeat_file()

    # ── Public API ────────────────────────────────────────────────────────────

    def tick(self) -> HeartbeatTickResult:
        """Execute one heartbeat cycle (synchronous, called via to_thread)."""
        t0 = time.monotonic()

        with self._lock:
            self._force_tick = False

        # ① activeHours check
        if not self._in_active_hours():
            result = HeartbeatTickResult(outcome="skip", reason="outside active hours")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — outside active hours")
            return result

        # ② Read HEARTBEAT.md
        content = self.read_file().strip()
        if not content:
            result = HeartbeatTickResult(outcome="skip", reason="HEARTBEAT.md is empty")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — HEARTBEAT.md empty")
            return result

        # ③ ESCALATE budget check
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if self._escalate_date != today:
                self._escalate_date = today
                self._escalate_count = 0
            budget_exceeded = self._escalate_count >= self._cfg.max_escalations_per_day

        # ④ Tier-1 precheck
        response = self._checker.precheck(content)
        duration_ms = int((time.monotonic() - t0) * 1000)

        if response.strip().upper().startswith("HEARTBEAT_OK") or budget_exceeded:
            reason = "budget exceeded" if budget_exceeded else ""
            result = HeartbeatTickResult(outcome="ok", reason=reason, duration_ms=duration_ms)
            self._tick_log.append(result)
            logger.debug("[Heartbeat] HEARTBEAT_OK (budget_exceeded=%s)", budget_exceeded)
            return result

        # ⑤ Tier-2 ESCALATE
        escalate_reason = response.replace("ESCALATE:", "").strip()
        with self._lock:
            self._escalate_count += 1

        logger.info("[Heartbeat] ESCALATE: %s", escalate_reason[:100])
        answer = ""
        answer = self._checker.run_escalate(escalate_reason, content)

        duration_ms = int((time.monotonic() - t0) * 1000)
        result = HeartbeatTickResult(
            outcome="escalate",
            reason=escalate_reason[:200],
            duration_ms=duration_ms,
        )
        self._tick_log.append(result)
        return result

    def force_tick(self) -> None:
        """Signal Clock to trigger a proactive tick on the next loop iteration."""
        with self._lock:
            self._force_tick = True

    def read_file(self) -> str:
        path = self._cfg.heartbeat_file
        if not os.path.isabs(path):
            path = os.path.join(self._scheduler_dir, os.path.basename(path))
        if not os.path.exists(path):
            return ""
        with open(path, encoding="utf-8") as f:
            return f.read()

    def write_file(self, content: str) -> None:
        path = self._cfg.heartbeat_file
        if not os.path.isabs(path):
            path = os.path.join(self._scheduler_dir, os.path.basename(path))
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def recent_log(self, n: int = 50) -> list[dict]:
        return self._tick_log.recent(n)

    # ── Helpers ───────────────────────────────────────────────────────────────

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

    def _ensure_heartbeat_file(self) -> None:
        path = self._cfg.heartbeat_file
        if not os.path.isabs(path):
            path = os.path.join(self._scheduler_dir, os.path.basename(path))
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_HEARTBEAT_MD)
            logger.info("[Heartbeat] created default HEARTBEAT.md at %s", path)
