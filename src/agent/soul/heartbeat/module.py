from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone

from runtime.scheduler.heartbeat_config import HeartbeatConfig
from agent.soul.heartbeat.checker import HeartbeatChecker
from agent.soul.heartbeat.tick_log import HeartbeatTickLog, HeartbeatTickResult

logger = logging.getLogger(__name__)

_DEFAULT_HEARTBEAT_MD = """\
# Heartbeat Checklist

- 检查时间线，有无 1 小时内到期的任务？如有，酌情提前通知用户。
- 有无 pending 超过 24h 的任务？是否需要重新安排？
- 无事可做时，只回复 HEARTBEAT_OK。
"""


class HeartbeatModule:
    """Agent-layer proactive heartbeat. Injected into ``runtime.scheduler`` via ``HeartbeatProtocol``."""

    def __init__(
        self,
        cfg: HeartbeatConfig,
        scheduler_dir: str,
        llm_service,
        llm_cfg_path: str,
        scheduler_engine,
        scheduler_cfg,
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
        self._daily_review_date: str = ""
        self._life_manager = None
        self._persona_manager = None
        self._lock = threading.Lock()
        self._ensure_heartbeat_file()

    def tick(self) -> HeartbeatTickResult:
        t0 = time.monotonic()

        with self._lock:
            self._force_tick = False

        if not self._in_active_hours():
            result = HeartbeatTickResult(outcome="skip", reason="outside active hours")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — outside active hours")
            return result

        content = self.read_file().strip()
        if not content:
            result = HeartbeatTickResult(outcome="skip", reason="HEARTBEAT.md is empty")
            self._tick_log.append(result)
            logger.debug("[Heartbeat] skip — HEARTBEAT.md empty")
            return result

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            if self._escalate_date != today:
                self._escalate_date = today
                self._escalate_count = 0
            budget_exceeded = self._escalate_count >= self._cfg.max_escalations_per_day

        self._run_life_hooks(today)

        response = self._checker.precheck(content)
        duration_ms = int((time.monotonic() - t0) * 1000)

        if response.strip().upper().startswith("HEARTBEAT_OK") or budget_exceeded:
            reason = "budget exceeded" if budget_exceeded else ""
            inject = ""
            if self._cfg.inject_on_ok and not budget_exceeded:
                inject = "[心跳] 本轮清单检查完成（HEARTBEAT_OK）。"
            elif self._cfg.inject_on_ok and budget_exceeded:
                inject = "[心跳] 今日主动介入次数已达上限，跳过 escalate。"
            result = HeartbeatTickResult(
                outcome="ok",
                reason=reason,
                duration_ms=duration_ms,
                detail_for_inject=inject,
            )
            self._tick_log.append(result)
            logger.debug("[Heartbeat] HEARTBEAT_OK (budget_exceeded=%s)", budget_exceeded)
            return result

        escalate_reason = response.replace("ESCALATE:", "").strip()
        with self._lock:
            self._escalate_count += 1

        logger.info("[Heartbeat] ESCALATE: %s", escalate_reason[:100])
        answer = self._checker.run_escalate(escalate_reason, content)

        duration_ms = int((time.monotonic() - t0) * 1000)
        body = (answer or "")[:6000]
        inject_text = (
            f"【心跳-待办】{escalate_reason[:500]}\n\n{body}".strip()
        )
        result = HeartbeatTickResult(
            outcome="escalate",
            reason=escalate_reason[:200],
            duration_ms=duration_ms,
            detail_for_inject=inject_text,
        )
        self._tick_log.append(result)
        return result

    def set_life_manager(self, life_manager) -> None:
        self._life_manager = life_manager

    def set_persona_manager(self, persona_manager) -> None:
        self._persona_manager = persona_manager

    @property
    def pending_force(self) -> bool:
        with self._lock:
            return self._force_tick

    def force_tick(self) -> None:
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

    def _run_life_hooks(self, today: str) -> None:
        lm = self._life_manager
        if lm is None:
            return

        tasks_text = self._format_recent_tasks()
        if tasks_text:
            lm.record_scheduler_digest_from_heartbeat(tasks_text)
            logger.debug("[Life] recorded scheduler digest")

        with self._lock:
            needs_review = self._daily_review_date != today

        if needs_review:
            with self._lock:
                self._daily_review_date = today
            self._run_daily_review(lm)
            self._run_self_concept_evolution()

    def _format_recent_tasks(self) -> str:
        if self._checker._scheduler_engine is None:
            return ""
        timeline = self._checker._scheduler_engine.list_timeline()
        completed = [
            t for t in timeline
            if hasattr(t, "status") and str(t.status.value) in ("done", "completed")
        ]
        if not completed:
            return ""
        parts = []
        for t in completed[-5:]:
            name = getattr(t, "name", "")
            result = getattr(t, "result", "") or ""
            if name:
                parts.append(f"- {name}: {str(result)[:80]}")
        return "\n".join(parts)

    def _run_self_concept_evolution(self, ruminations: list | None = None) -> None:
        """触发 SelfConcept 日终演化。

        ruminations 可由 LifeManager 日终回顾后从 LTM 查询到的
        ReconstructiveMemory 列表传入，提升叙事更新质量。
        MVP 阶段若无来源，传 None 即可，退化为仅用情绪锚点。
        """
        pm = self._persona_manager
        if pm is None:
            return
        changed = pm.evolve_self_concept(recent_ruminations=ruminations)
        logger.debug("[SelfConcept] daily evolution done, changed=%s", changed)

    def _run_daily_review(self, lm) -> None:
        pm = self._persona_manager
        if pm is None:
            logger.debug("[Life] daily review skipped — no persona_manager")
            return

        engine = self._checker._scheduler_engine
        today_tasks = self._format_recent_tasks()
        out = lm.run_daily_review(
            static_profile=pm.profile,
            today_medium_term="",
            today_scheduler_tasks=today_tasks,
            scheduler_engine=engine,
        )
        if out is None:
            return
        result, life_ctx = out
        if life_ctx is not None and not life_ctx.is_empty():
            pm.status.receive_life_context(life_ctx, trigger_update=True)
        logger.info(
            "[Life] daily review complete — %d scheduler actions, %d thought lines",
            len(result.scheduler_actions),
            len(result.thought_records),
        )

    def _ensure_heartbeat_file(self) -> None:
        path = self._cfg.heartbeat_file
        if not os.path.isabs(path):
            path = os.path.join(self._scheduler_dir, os.path.basename(path))
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_DEFAULT_HEARTBEAT_MD)
            logger.info("[Heartbeat] created default HEARTBEAT.md at %s", path)
