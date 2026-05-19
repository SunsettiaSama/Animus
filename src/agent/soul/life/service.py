from __future__ import annotations

import threading
from collections.abc import Callable

from agent.soul.heartbeat.bridge import MemoryHeartbeatResult

from agent.soul.workers import DomainWorker

from .anchor import RealityAnchorLayer
from .experience.unit import ExperienceActionKind
from .virtual import VirtualLayer


class LifeService(DomainWorker):
    """Life 域 worker：Heartbeat / TaoLoop 只入队，重活在 life-worker 线程执行。"""

    def __init__(
        self,
        anchor: RealityAnchorLayer,
        virtual: VirtualLayer,
    ) -> None:
        super().__init__("life-worker")
        self._anchor = anchor
        self._virtual = virtual
        self._pending_landmark_fills: set[str] = set()
        self._landmark_lock = threading.Lock()

    @property
    def anchor(self) -> RealityAnchorLayer:
        return self._anchor

    @property
    def virtual(self) -> VirtualLayer:
        return self._virtual

    def start(self, **kwargs) -> None:
        if self._thread and self._thread.is_alive():
            return
        for lm in self._virtual.scan_overdue_landmarks():
            self._enqueue_landmark_fill(lm.id)
        super().start()

    def status(self) -> dict:
        base = super().status()
        fragment = self._virtual.status_fragment()
        with self._landmark_lock:
            pending_fills = len(self._pending_landmark_fills)
        return {**base, "pending_landmark_fills": pending_fills, **fragment}

    def trigger_due_landmarks(self) -> dict:
        due = self._virtual.due_landmarks()
        self.enqueue(lambda: self._anchor.builder.orchestrator.tick())
        for lm in due:
            self._enqueue_landmark_fill(lm.id)
        return {
            "due_found": len(due),
            "queued": self._queue_depth(),
            "async": True,
        }

    def tick_surprise(self, elapsed_sec: float) -> dict:
        self.enqueue(lambda: self._virtual.tick_surprise(elapsed_sec=elapsed_sec))
        return {"queued": True, "queue_depth": self._queue_depth()}

    def enqueue_wander_experience(
        self,
        result: MemoryHeartbeatResult,
        profile_narrative: str,
    ) -> None:
        self.enqueue(
            lambda: self._virtual.process_wander_experience(result, profile_narrative)
        )

    def enqueue_scheduler_digest(self, tasks_text: str) -> None:
        self.enqueue(lambda: self._anchor.record_scheduler_digest(tasks_text))

    def enqueue_plan_landmark(self, job: Callable[[], object]) -> None:
        self.enqueue(job)

    def update_context(
        self,
        profile_narrative: str = "",
        recent_memories: list[str] | None = None,
    ) -> None:
        self._virtual.update_context(
            profile_narrative=profile_narrative,
            recent_memories=recent_memories,
        )

    def set_filler(self, filler) -> None:
        self._virtual.set_filler(filler)

    def set_surprise_generator(self, generator) -> None:
        self._virtual.set_surprise_generator(generator)

    def enqueue_user_turn(
        self,
        session_id: str,
        user_text: str,
        agent_reply: str,
        salience: float = 0.3,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        activated_memory_ids: list[str] | None = None,
    ) -> None:
        self.enqueue(lambda: self._anchor.record_user_turn(
            session_id=session_id,
            user_text=user_text,
            agent_reply=agent_reply,
            salience=salience,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            activated_memory_ids=activated_memory_ids,
        ))

    def enqueue_story_beat(
        self,
        narrative_hint: str,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
        virtual_ctx=None,
    ) -> None:
        self.enqueue(lambda: self._virtual.record_story_beat(
            narrative_hint=narrative_hint,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            salience=salience,
            action_kind=action_kind,
            virtual_ctx=virtual_ctx,
        ))

    def _enqueue_landmark_fill(self, landmark_id: str) -> None:
        with self._landmark_lock:
            if landmark_id in self._pending_landmark_fills:
                return
            self._pending_landmark_fills.add(landmark_id)

        def _run() -> None:
            lm = self._virtual.journal.get_landmark(landmark_id)
            if lm is not None and lm.status.value == "pending":
                lm.mark_overdue()
            self._virtual.fill_landmark(landmark_id)
            with self._landmark_lock:
                self._pending_landmark_fills.discard(landmark_id)

        self.enqueue(_run)
