from __future__ import annotations

from collections.abc import Callable

from infra.llm import BaseLLM
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
from agent.soul.life.life_bridge import LifeContextInput

from .anchor import AnchorLayer, RealityAnchorLayer, ProactiveOutboundIntent, ProactiveOutboundPort
from .virtual import VirtualLayer
from .profile import LifeProfile, LifeProfileStore
from .experience import (
    DialogueExperiencePipeline,
    ExperienceBuilder,
    LifeExperiencePipeline,
)
from .anchor.chronicle import AnchorChronicleStore
from .virtual.chronicle import VirtualChronicleStore
from .narrative_context import NarrativeContextSupplier, StoryWorldContextSupplier
from .virtual.narrative import NarrativeEngine
from .virtual.review import build_life_context_from_chronicle
from .service import LifeService


class LifeManager:
    """Life 模块统一入口：虚拟叙事层 + 锚点 chronicle；生活体验由 life/experience 维护。"""

    def __init__(
        self,
        life_dir: str,
        llm: BaseLLM | None = None,
    ) -> None:
        self._life_dir = life_dir
        self._virtual_chronicle = VirtualChronicleStore(life_dir)
        anchor_chronicle = AnchorChronicleStore(life_dir)
        self._anchor = AnchorLayer(
            life_dir=life_dir,
            chronicle=anchor_chronicle,
        )
        self._experience: LifeExperiencePipeline | None = None
        self._dialogue_experience: DialogueExperiencePipeline | None = None
        self._builder: ExperienceBuilder | None = None
        self._virtual = VirtualLayer(
            builder=None,
            life_dir=life_dir,
            llm=llm,
            chronicle=self._virtual_chronicle,
        )

        self._life_service = LifeService(anchor=self._anchor, virtual=self._virtual)

        self._profile_store = LifeProfileStore(life_dir)
        self._profile: LifeProfile = LifeProfile()

    def attach_life_experience(self, pipeline: LifeExperiencePipeline) -> None:
        self._experience = pipeline
        self._builder = pipeline.builder
        self._virtual.set_builder(pipeline.builder)
        if self._virtual.narrative is not None:
            pipeline.set_collapser(self._virtual.narrative)
        self._life_service.set_experience_tick(pipeline.tick)

    def attach_dialogue_experience(self, pipeline: DialogueExperiencePipeline) -> None:
        self._dialogue_experience = pipeline

    def attach_experience_pipeline(
        self,
        life: LifeExperiencePipeline,
        *,
        dialogue: DialogueExperiencePipeline | None = None,
    ) -> None:
        """挂载生活体验；可选同时挂载对话体验（出站 open_outbound）。"""
        self.attach_life_experience(life)
        if dialogue is not None:
            self.attach_dialogue_experience(dialogue)

    @property
    def experience(self) -> LifeExperiencePipeline | None:
        return self._experience

    @property
    def worker(self) -> LifeService:
        return self._life_service

    @property
    def anchor(self) -> RealityAnchorLayer:
        return self._anchor

    @property
    def virtual(self) -> VirtualLayer:
        return self._virtual

    @property
    def narrative(self) -> NarrativeEngine | None:
        return self._virtual.narrative

    @property
    def journal(self):
        return self._virtual.journal

    @property
    def profile(self) -> LifeProfile:
        return self._profile

    def save_journal(self) -> None:
        self._virtual.save_journal()

    def add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> bool:
        return self._virtual.add_landmark(intention, scheduled_at, context)

    def plan_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> dict | None:
        return self._virtual.plan_landmark(intention, scheduled_at, context)

    def enqueue_add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> None:
        self._life_service.enqueue(
            lambda: self._virtual.add_landmark(intention, scheduled_at, context)
        )

    def enqueue_compose_and_plan(self, job: Callable[[], dict]) -> None:
        self._life_service.enqueue_plan_landmark(job)

    def set_landmark_filler(self, filler) -> None:
        self._virtual.set_filler(filler)
        self._life_service.set_filler(filler)

    def set_surprise_generator(self, generator) -> None:
        self._virtual.set_surprise_generator(generator)
        self._life_service.set_surprise_generator(generator)

    def set_narrative_engine(self, engine: NarrativeEngine) -> None:
        self._virtual.set_narrative_engine(engine)
        if self._experience is not None and engine is not None:
            self._experience.set_collapser(engine)
        self._life_service.set_filler(engine)
        self._life_service.set_surprise_generator(engine)

    def set_memory_port(self, port) -> None:
        if self._experience is not None:
            self._experience.set_memory_port(port)

    def set_narrative_context_supplier(
        self, supplier: NarrativeContextSupplier | None
    ) -> None:
        self._virtual.set_narrative_context_supplier(supplier)

    def set_story_world_context_supplier(
        self,
        supplier: StoryWorldContextSupplier | None,
    ) -> None:
        self._virtual.set_story_world_context_supplier(supplier)

    def set_story_port(self, port) -> None:
        self._virtual.set_story_port(port)

    def bind_story_world(self, world_id: str) -> None:
        token = world_id.strip() or "default"
        self._profile.world_id = token
        self._virtual.set_world_id(token)

    def save_profile(self) -> None:
        self._profile_store.save(self._profile)

    def stop(self) -> None:
        self._life_service.stop()

    def service_status(self) -> dict:
        return self._life_service.status()

    def count_landmarks_written_since(self, since_iso: str) -> int:
        return self._virtual.count_landmarks_written_since(since_iso)

    def compose_landmark(self) -> dict | None:
        return self._virtual.compose_landmark()

    def trigger_due_landmarks(self) -> dict:
        return self._life_service.trigger_due_landmarks()

    def tick_surprise(self, elapsed_sec: float) -> dict:
        return self.run_surprise_tick(elapsed_sec)

    def run_surprise_tick(self, elapsed_sec: float) -> dict:
        return self._virtual.tick_surprise(elapsed_sec=elapsed_sec)

    def fill_due_landmarks(self) -> list[dict]:
        filled: list[dict] = []
        for lm in list(self._virtual.due_landmarks()):
            item = self._virtual.fill_landmark(lm.id)
            if item is not None:
                filled.append(item)
        return filled

    def build_life_context(self, days: int = 1) -> LifeContextInput:
        return build_life_context_from_chronicle(
            self._anchor.chronicle,
            virtual_store=self._virtual_chronicle,
            days=days,
        )

    def format_dialogue_digest(self, days: int = 1) -> str:
        return self._anchor.chronicle.format_dialogue_digest(days=days)

    def record_scheduler_digest_from_heartbeat(self, tasks_text: str) -> None:
        self._life_service.enqueue_scheduler_digest(tasks_text)

    def submit_proactive_outbound(
        self,
        message: str,
        *,
        reason: str = "",
        session_id: str = "tao",
        salience: float = 0.4,
    ) -> str:
        intent_id = self._anchor.submit_proactive_outbound(
            message,
            reason=reason,
            session_id=session_id,
            salience=salience,
        )
        if self._dialogue_experience is not None:
            self._dialogue_experience.open_outbound(
                session_id,
                message,
                proactive_intent_id=intent_id,
            )
        return intent_id

    def pending_proactive_outbounds(self) -> list[ProactiveOutboundIntent]:
        return self._anchor.pending_proactive_outbounds()

    def receive_experience(self, result: MemoryHeartbeatResult) -> None:
        self._life_service.enqueue(
            lambda: self.apply_wander_experience(result)
        )

    def apply_wander_experience(self, result: MemoryHeartbeatResult) -> list[dict]:
        """Wander 体验入账；须在 life-worker 线程内执行。"""
        return self._virtual.process_wander_experience(result)

    def load_profile(self) -> LifeProfile:
        self._profile = self._profile_store.load()
        if self._profile.world_id.strip():
            self._virtual.set_world_id(self._profile.resolved_world_id())
        return self._profile

    def sync_agent_persona_narrative(self, narrative: str) -> None:
        self.worker.update_context(profile_narrative=narrative.strip())

    def recent_chronicle(self, *, days: int = 7, tail: int = 50) -> list[dict]:
        anchor = self._anchor.chronicle.recent_days(days)
        virtual = self._virtual_chronicle.recent_days(days)
        merged = sorted(
            [e.to_dict() for e in anchor] + [e.to_dict() for e in virtual],
            key=lambda d: d.get("ts", ""),
        )
        if tail > 0 and len(merged) > tail:
            merged = merged[-tail:]
        return merged

    def recent_anchor_chronicle(self, *, days: int = 7, tail: int = 50) -> list[dict]:
        entries = self._anchor.chronicle.recent_days(days)
        if tail > 0 and len(entries) > tail:
            entries = entries[-tail:]
        return [e.to_dict() for e in entries]

    def recent_virtual_chronicle(self, *, days: int = 7, tail: int = 50) -> list[dict]:
        entries = self._virtual_chronicle.recent_days(days)
        if tail > 0 and len(entries) > tail:
            entries = entries[-tail:]
        return [e.to_dict() for e in entries]

    def hot_experiences(self, *, hours: int | None = None) -> list[dict]:
        if self._experience is None:
            return []
        return self._experience.hot_experiences(hours=hours)
