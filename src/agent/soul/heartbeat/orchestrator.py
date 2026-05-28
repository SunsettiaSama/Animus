from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agent.soul.heartbeat.console_log import hb_debug
from config.soul.config import SoulConfig
from agent.soul.handlers.api.actions import LifeAction, MemoryAction, PersonaAction
from agent.soul.presence.actions import PresenceAction
from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

if TYPE_CHECKING:
    from agent.soul.service import SoulService
    from .worker import SoulEvolutionWorker

from .checklist import ChecklistItem, ChecklistRegistry, default_checklist
from .evolution_capture import EvolutionBeat, EvolutionCapture

logger = logging.getLogger(__name__)
_PRESENCE_SCAN_EXTERNAL_ACTION = PresenceAction.SCAN_EXTERNAL

_HEAVY_ITEM_KEYS: frozenset[tuple[str, str]] = frozenset({
    (SoulDomain.memory.value, MemoryAction.WANDER),
    (SoulDomain.memory.value, MemoryAction.FORGET_SCAN),
    (SoulDomain.memory.value, MemoryAction.SLEEP),
    (SoulDomain.life.value, LifeAction.PLAN_LANDMARK),
    (SoulDomain.persona.value, PersonaAction.RUN_MONTHLY_DRIFT),
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

    def run_due(self, *, exclude_item_ids: frozenset[str] = frozenset()) -> list[ChecklistRunResult]:
        if self._soul is None:
            return []

        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        results: list[ChecklistRunResult] = []

        for item in self._checklist.due(now_mono, now_dt):
            if item.id in exclude_item_ids:
                continue
            if self.is_heavy(item):
                result = self._enqueue_heavy(item, now_mono, now_dt)
            else:
                result = self.execute_item(item)
                if result.ok:
                    self._checklist.mark_run(item, now_mono, now_dt)
            results.append(result)
            hb_debug(
                logger,
                "[HeartbeatOrchestrator] %s/%s ok=%s async=%s",
                item.domain,
                item.action,
                result.ok,
                result.async_enqueued,
            )

        return results

    def run_due_item(self, item_id: str) -> ChecklistRunResult | None:
        if self._soul is None:
            return None

        item = self._checklist._items.get(item_id)
        if item is None or not item.enabled:
            return None

        now_mono = time.monotonic()
        now_dt = datetime.now(timezone.utc)
        due_ids = {i.id for i in self._checklist.due(now_mono, now_dt)}
        if item_id not in due_ids:
            return None

        if self.is_heavy(item):
            result = self._enqueue_heavy(item, now_mono, now_dt)
        else:
            result = self.execute_item(item)
            if result.ok:
                self._checklist.mark_run(item, now_mono, now_dt)
        hb_debug(
            logger,
            "[HeartbeatOrchestrator] %s/%s ok=%s async=%s",
            item.domain,
            item.action,
            result.ok,
            result.async_enqueued,
        )
        return result

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
        if item.domain == SoulDomain.memory.value and item.action == MemoryAction.SLEEP:
            return self._run_memory_sleep(item)
        if item.domain == "presence" and item.action == PresenceAction.WAKE_UP:
            return self._run_presence_wake(item)
        if item.domain == "presence" and item.action == PresenceAction.SLEEP:
            return self._run_presence_sleep(item)
        if item.domain == "presence" and item.action == _PRESENCE_SCAN_EXTERNAL_ACTION:
            return self._run_scan_external(item)
        if item.domain == "presence" and item.action == PresenceAction.SCAN_EXPECTATION:
            return self._run_scan_expectation(item)
        if item.domain == SoulDomain.life.value and item.action == LifeAction.PLAN_LANDMARK:
            return self._run_plan_landmark(item)
        if item.domain == SoulDomain.life.value and item.action == LifeAction.TRIGGER_LANDMARKS:
            return self._run_trigger_landmarks(item)
        if item.domain == SoulDomain.life.value and item.action == LifeAction.TICK_SURPRISE:
            return self._run_tick_surprise(item)
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
        capture_report = None
        if detail.get("planned"):
            subjective_event = dict(detail.get("subjective_event", {}))
            if subjective_event.get("hint"):
                capture_report = EvolutionCapture.after_landmark_planned(
                    self._soul,
                    subjective_event,
                )
        if capture_report is not None:
            detail = {
                **detail,
                "capture_events": len(capture_report.events),
                "capture_outbound": capture_report.outbound_count,
                "incident_fsm_updates": capture_report.incident_count,
            }
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_memory_sleep(self, item: ChecklistItem) -> ChecklistRunResult:
        dry_run = bool(item.payload.get("dry_run", False))
        detail = self._soul.run_memory_sleep(dry_run=dry_run)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_wander(self, item: ChecklistItem) -> ChecklistRunResult:
        result, story_beats = self._soul.run_wander()
        capture_report = EvolutionCapture.after_wander(
            self._soul,
            result,
            self._beats_from_dicts(story_beats),
        )
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
                "flushed": result.forgotten_count,
                "forgotten": result.forgotten_count,
                "narrative_triggered": result.narrative_triggered,
                "story_beats": len(story_beats),
                "buffer_signals": len(result.buffer_candidates),
                "capture_events": len(capture_report.events),
                "capture_outbound": capture_report.outbound_count,
                "rumination_fsm": capture_report.rumination_count,
            },
        )

    def _run_trigger_landmarks(self, item: ChecklistItem) -> ChecklistRunResult:
        fills = self._soul.run_trigger_landmarks()
        capture_report = EvolutionCapture.after_landmark_filled(
            self._soul,
            self._beats_from_dicts(fills),
        )
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail={
                "filled": len(fills),
                "capture_events": len(capture_report.events),
                "capture_outbound": capture_report.outbound_count,
                "incident_fsm_updates": capture_report.incident_count,
            },
        )

    def _run_tick_surprise(self, item: ChecklistItem) -> ChecklistRunResult:
        elapsed = float(item.payload.get("elapsed_sec", self._cfg.surprise_tick_interval_sec))
        detail = self._soul.run_surprise_tick(elapsed)
        capture_report = None
        if detail.get("triggered"):
            capture_report = EvolutionCapture.after_surprise(
                self._soul,
                hint=str(detail.get("narrative", "")),
                salience=float(detail.get("salience", 0.5)),
                emotion_text=str(detail.get("emotion_text", "")),
                emotion_intensity=float(detail.get("emotion_intensity", 0.0)),
                emotion_strength=str(detail.get("emotion_strength", "")),
            )
        if capture_report is not None:
            detail = {
                **detail,
                "capture_events": len(capture_report.events),
                "capture_outbound": capture_report.outbound_count,
                "incident_fsm_updates": capture_report.incident_count,
            }
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_scan_expectation(self, item: ChecklistItem) -> ChecklistRunResult:
        session_id = str(item.payload.get("session_id", "tao"))
        detail = self._soul.run_expectation_scan(session_id=session_id)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_scan_external(self, item: ChecklistItem) -> ChecklistRunResult:
        session_id = str(item.payload.get("session_id", "tao"))
        detail = self._soul.run_external_opportunity_scan(session_id=session_id)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            True,
            detail=detail,
        )

    def _run_presence_wake(self, item: ChecklistItem) -> ChecklistRunResult:
        session_id = str(item.payload.get("session_id", "tao"))
        detail = self._soul.run_presence_wake(session_id=session_id)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            bool(detail.get("ok")),
            detail=detail,
        )

    def _run_presence_sleep(self, item: ChecklistItem) -> ChecklistRunResult:
        session_id = str(item.payload.get("session_id", "tao"))
        detail = self._soul.run_presence_sleep(session_id=session_id)
        return ChecklistRunResult(
            item.id,
            item.domain,
            item.action,
            bool(detail.get("ok")),
            detail=detail,
        )

    @staticmethod
    def _beats_from_dicts(items: list[dict]) -> list[EvolutionBeat]:
        return [
            EvolutionBeat(
                hint=str(item.get("hint", "")),
                salience=float(item.get("salience", 0.4)),
                trigger=str(item.get("trigger", "")),
                source=str(item.get("source", "")),
                share_desire=str(item.get("share_desire", "")),
                emotion_text=str(item.get("emotion_text", "")),
                emotion_intensity=float(item.get("emotion_intensity", 0.0)),
                emotion_strength=str(item.get("emotion_strength", "")),
            )
            for item in items
        ]

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
