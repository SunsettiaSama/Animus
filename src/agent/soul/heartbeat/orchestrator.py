from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from config.soul.config import SoulConfig
from agent.soul.handlers.api.actions import LifeAction, MemoryAction
from agent.soul.handlers.tao.actions import TaoPersonaAction
from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

if TYPE_CHECKING:
    from agent.soul.service import SoulService
    from .worker import SoulEvolutionWorker

from .checklist import ChecklistItem, ChecklistRegistry, default_checklist

logger = logging.getLogger(__name__)

_HEAVY_ITEM_KEYS: frozenset[tuple[str, str]] = frozenset({
    (SoulDomain.memory.value, MemoryAction.WANDER),
    (SoulDomain.memory.value, MemoryAction.FLUSH),
    (SoulDomain.life.value, LifeAction.PLAN_LANDMARK),
    (SoulDomain.persona.value, TaoPersonaAction.RUN_DAILY_REFLECTION),
})


@dataclass
class ChecklistRunResult:
    item_id: str
    domain: str
    action: str
    ok: bool
    detail: Any = None
    error: str = ""
    async_enqueued: bool = False


class HeartbeatOrchestrator:
    """心跳编排器：扫描 checklist，轻量项同步执行，重项入 SoulEvolutionWorker。"""

    def __init__(
        self,
        soul: SoulService | None = None,
        checklist: ChecklistRegistry | None = None,
        *,
        soul_config: SoulConfig | None = None,
    ) -> None:
        self._soul = soul
        self._cfg = soul_config or SoulConfig.default()
        self._checklist = checklist or ChecklistRegistry(cfg=self._cfg)
        self._scheduler_engine = None
        self._worker: SoulEvolutionWorker | None = None

    @property
    def soul_config(self) -> SoulConfig:
        return self._cfg

    @property
    def checklist(self) -> ChecklistRegistry:
        return self._checklist

    def set_soul_service(self, soul: SoulService | None) -> None:
        self._soul = soul
        if soul is not None:
            self._cfg = soul.config

    def set_scheduler_engine(self, engine) -> None:
        self._scheduler_engine = engine

    def set_worker(self, worker: SoulEvolutionWorker | None) -> None:
        self._worker = worker

    @staticmethod
    def is_heavy(item: ChecklistItem) -> bool:
        return (item.domain, item.action) in _HEAVY_ITEM_KEYS

    def run_due(self) -> list[ChecklistRunResult]:
        if self._soul is None:
            return []

        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        results: list[ChecklistRunResult] = []

        for item in self._checklist.due(now_mono, now_dt):
            if self.is_heavy(item):
                result = self._enqueue_heavy(item, now_mono, now_dt)
            else:
                result = self.execute_item(item)
                if result.ok:
                    self._checklist.mark_run(item, now_mono, now_dt)
            results.append(result)
            logger.debug(
                "[HeartbeatOrchestrator] %s/%s ok=%s async=%s",
                item.domain,
                item.action,
                result.ok,
                result.async_enqueued,
            )

        return results

    def _enqueue_heavy(
        self,
        item: ChecklistItem,
        now_mono: float,
        now_dt: datetime,
    ) -> ChecklistRunResult:
        if self._worker is None:
            result = self.execute_item(item)
            if result.ok:
                self._checklist.mark_run(item, now_mono, now_dt)
            return result

        if not self._worker.enqueue(item):
            return ChecklistRunResult(
                item.id,
                item.domain,
                item.action,
                True,
                detail={"skipped": "already pending"},
            )

        self._checklist.mark_run(item, now_mono, now_dt)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail={"enqueued": True},
            async_enqueued=True,
        )

    def execute_item(self, item: ChecklistItem) -> ChecklistRunResult:
        if self._soul is None:
            return ChecklistRunResult(
                item.id, item.domain, item.action, False, error="no soul"
            )

        if item.domain == SoulDomain.memory.value and item.action == MemoryAction.WANDER:
            return self._run_wander(item)
        if item.domain == SoulDomain.life.value and item.action == LifeAction.PLAN_LANDMARK:
            return self._run_plan_landmark(item)
        if item.channel == SoulChannel.tao.value and (
            item.domain == SoulDomain.persona.value
            and item.action == TaoPersonaAction.RUN_DAILY_REFLECTION
        ):
            return self._run_persona_daily_reflection(item)
        if item.domain == SoulDomain.life.value and item.action == LifeAction.RECORD_SCHEDULER_DIGEST:
            tasks_text = self._format_recent_tasks()
            if not tasks_text.strip():
                return ChecklistRunResult(
                    item.id, item.domain, item.action, True, detail="skip empty"
                )
            self._soul.dispatch(SoulRequest(
                domain=SoulDomain.life,
                action=LifeAction.RECORD_SCHEDULER_DIGEST,
                payload={"tasks_text": tasks_text},
                channel=SoulChannel.api,
            ))
            return ChecklistRunResult(item.id, item.domain, item.action, True)

        channel = SoulChannel(item.channel)
        domain = SoulDomain(item.domain)
        payload = dict(item.payload)
        detail = self._soul.dispatch(SoulRequest(
            domain=domain,
            action=item.action,
            payload=payload,
            channel=channel,
        ))
        return ChecklistRunResult(item.id, item.domain, item.action, True, detail=detail)

    def _run_plan_landmark(self, item: ChecklistItem) -> ChecklistRunResult:
        life_worker = self._soul.workers.life
        detail = life_worker.submit(
            lambda: self._soul.execute_plan_landmark()
        ).result()
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_wander(self, item: ChecklistItem) -> ChecklistRunResult:
        result = self._soul.run_wander()
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail={
                "tick_id": result.tick_id,
                "wandered": len(result.wandered_ids),
                "ruminated": len(result.ruminated_ids),
                "intensity": result.signal.intensity,
                "dominant_emotion": result.signal.dominant_emotion,
                "flushed": result.flushed_count,
                "narrative_triggered": result.narrative_triggered,
            },
        )

    def _run_persona_daily_reflection(self, item: ChecklistItem) -> ChecklistRunResult:
        lm = self._soul.life.api
        detail = self._soul.dispatch_tao(SoulRequest(
            domain=SoulDomain.persona,
            action=TaoPersonaAction.RUN_DAILY_REFLECTION,
            payload={
                "today_dialogue": lm.format_dialogue_digest(days=1),
                "today_scheduler_tasks": self._format_recent_tasks(),
            },
            channel=SoulChannel.tao,
        ))
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            bool(detail.get("ok")),
            detail=detail,
        )

    def _format_recent_tasks(self) -> str:
        if self._scheduler_engine is None:
            return ""
        timeline = self._scheduler_engine.list_timeline()
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
