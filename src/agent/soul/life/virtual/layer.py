from __future__ import annotations

from datetime import datetime
from typing import Callable

from infra.llm import BaseLLM

from agent.soul.heartbeat.bridge import MemoryHeartbeatResult

from ..experience import ExperienceBuilder, ExperienceActionKind, ExperienceUnit
from ..narrative_context import (
    NarrativeContextSupplier,
    NarrativePurpose,
    StoryWorldContextSupplier,
)
from .chronicle import VirtualChronicleStore
from .journal.dice import DiceResult, roll_d100
from .journal.filler import LandmarkFiller, NullLandmarkFiller
from .journal.item import Landmark, LandmarkStatus
from .journal.journal import LifeJournal
from .journal.store import JournalStore
from .narrative import NarrativeEngine
from agent.soul.life.experience.domain.virtual_codec import VirtualUnitContext, VirtualUnitTrigger
from .surprise.generator import NullSurpriseGenerator, SurpriseGenerator
from .surprise.launcher import SurpriseLauncher


class VirtualLayer:
    """虚拟层：故事驱动、手账地标、命运骰与意外事件。

    所有经本层写入的体验单元 ``source`` 为 ``narrative`` 或 ``surprise``，
    仍走同一 ``ExperienceBuilder`` → ``ExperienceOrchestrator`` 链路。
    """

    def __init__(
        self,
        builder: ExperienceBuilder | None,
        life_dir: str,
        llm: BaseLLM | None = None,
        chronicle: VirtualChronicleStore | None = None,
    ) -> None:
        self._builder = builder
        self._chronicle = chronicle or VirtualChronicleStore(life_dir)
        self._journal_store = JournalStore(life_dir)
        self._journal: LifeJournal = self._journal_store.load()
        self._narrative: NarrativeEngine | None = (
            NarrativeEngine(llm) if llm is not None else None
        )
        self._filler: LandmarkFiller = (
            self._narrative if self._narrative is not None else NullLandmarkFiller()
        )
        self._surprise_generator: SurpriseGenerator = (
            self._narrative if self._narrative is not None else NullSurpriseGenerator()
        )
        self._surprise_launcher = SurpriseLauncher()
        self._profile_narrative = ""
        self._continuity_memories: list[str] = []
        self._world_background = ""
        self._context_supplier: NarrativeContextSupplier | None = None
        self._world_context_supplier: StoryWorldContextSupplier | None = None

    @property
    def builder(self) -> ExperienceBuilder:
        if self._builder is None:
            raise RuntimeError("VirtualLayer builder not attached — wire presence/experience first")
        return self._builder

    def set_builder(self, builder: ExperienceBuilder) -> None:
        self._builder = builder

    @property
    def chronicle(self) -> VirtualChronicleStore:
        return self._chronicle

    @property
    def journal(self) -> LifeJournal:
        return self._journal

    @property
    def narrative(self) -> NarrativeEngine | None:
        return self._narrative

    @property
    def profile_narrative(self) -> str:
        return self._profile_narrative

    @property
    def continuity_memories(self) -> list[str]:
        return self._continuity_memories

    @property
    def world_background(self) -> str:
        return self._world_background

    @property
    def surprise_probability(self) -> float:
        return self._surprise_launcher.probability

    def set_narrative_engine(self, engine: NarrativeEngine | None) -> None:
        self._narrative = engine
        if engine is not None:
            self._filler = engine
            self._surprise_generator = engine
        else:
            self._filler = NullLandmarkFiller()
            self._surprise_generator = NullSurpriseGenerator()

    def set_filler(self, filler: LandmarkFiller) -> None:
        self._filler = filler

    def set_surprise_generator(self, generator: SurpriseGenerator) -> None:
        self._surprise_generator = generator

    def set_narrative_context_supplier(
        self, supplier: NarrativeContextSupplier | None
    ) -> None:
        self._context_supplier = supplier

    def set_story_world_context_supplier(
        self,
        supplier: StoryWorldContextSupplier | None,
    ) -> None:
        self._world_context_supplier = supplier

    def apply_narrative_context(
        self,
        portrait: str,
        continuity: list[str],
    ) -> None:
        self._profile_narrative = portrait
        self._continuity_memories = continuity

    def apply_world_background(self, background: str) -> None:
        self._world_background = background.strip()

    def ensure_narrative_context(
        self,
        purpose: NarrativePurpose,
        *,
        query: str = "",
    ) -> None:
        if self._context_supplier is not None:
            self._context_supplier.refresh(self, purpose, query=query)
        if self._world_context_supplier is not None:
            world = self._world_context_supplier.background(purpose, query=query)
            self.apply_world_background(world)

    def update_context(
        self,
        profile_narrative: str = "",
        continuity_memories: list[str] | None = None,
        world_background: str | None = None,
    ) -> None:
        if profile_narrative:
            self._profile_narrative = profile_narrative
        if continuity_memories is not None:
            self._continuity_memories = continuity_memories
        if world_background is not None:
            self._world_background = world_background

    def save_journal(self) -> None:
        self._journal_store.save(self._journal)

    def add_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> bool:
        return self.plan_landmark(intention, scheduled_at, context) is not None

    def plan_landmark(
        self,
        intention: str,
        scheduled_at: str,
        context: str = "",
    ) -> dict | None:
        lm = self._journal.add_landmark(intention, scheduled_at, context)
        if lm is None:
            return None
        self.save_journal()
        query = intention.strip()
        if context.strip():
            query = f"{query} {context.strip()}"
        self.ensure_narrative_context(NarrativePurpose.fabricate, query=query)

        plan_seed = f"我刚为自己预约了一个体验时刻：{intention.strip() or '一个新的地标'}"
        if context.strip():
            plan_seed = f"{plan_seed}。背景：{context.strip()}"
        plan_seed = f"{plan_seed}。触发时间：{scheduled_at}"

        narrative_hint = plan_seed
        emotion_text = ""
        emotion_intensity = 0.35
        emotion_strength = "轻微波动"
        if self._narrative is not None:
            draft = self._narrative.fabricate_with_emotion(
                hint=plan_seed,
                profile_narrative=self._profile_narrative,
                continuity_memories=self._continuity_memories,
                world_background=self._world_background,
                default_intensity=0.35,
            )
            narrative_hint = draft.narrative
            emotion_text = draft.emotion_text
            emotion_intensity = draft.emotion_intensity
            emotion_strength = draft.emotion_strength

        unit = self.record_story_beat(
            narrative_hint=narrative_hint,
            salience=emotion_intensity,
            emotion_label=emotion_strength,
            action_kind=ExperienceActionKind.deciding,
            virtual_ctx=VirtualUnitContext(
                trigger=VirtualUnitTrigger.landmark_plan,
                landmark_id=lm.id,
            ),
        )
        return {
            "hint": narrative_hint,
            "salience": emotion_intensity,
            "trigger": "landmark_plan",
            "source": "life",
            "share_desire": "mild",
            "emotion_text": emotion_text,
            "emotion_intensity": emotion_intensity,
            "emotion_strength": emotion_strength,
            "landmark_id": lm.id,
            "experience_id": unit.id,
        }

    def compose_landmark(self) -> dict | None:
        self.ensure_narrative_context(NarrativePurpose.compose)
        if self._narrative is None:
            return None
        return self._narrative.compose_landmark_intent(
            profile_narrative=self._profile_narrative,
            recent_landmark_intents=self._journal.recent_done_intent_lines(3),
            world_background=self._world_background,
        )

    def count_landmarks_written_since(self, since_iso: str) -> int:
        since = datetime.fromisoformat(since_iso.replace("Z", "+00:00"))
        return self._journal.count_written_since(since)

    def record_story_beat(
        self,
        narrative_hint: str,
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
        virtual_ctx: VirtualUnitContext | None = None,
    ) -> ExperienceUnit:
        return self._builder.record_story_beat(
            narrative_hint=narrative_hint,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            salience=salience,
            action_kind=action_kind,
            virtual_ctx=virtual_ctx,
        )

    def record_surprise(
        self,
        narrative_hint: str,
        dice_value: int = 0,
        dice_tendency: str = "",
        salience: float = 0.5,
    ) -> ExperienceUnit:
        return self._builder.record_surprise(
            narrative_hint=narrative_hint,
            dice_value=dice_value,
            dice_tendency=dice_tendency,
            salience=salience,
        )

    def scan_overdue_landmarks(self) -> list[Landmark]:
        overdue = self._journal.scan_overdue()
        if overdue:
            self.save_journal()
        return overdue

    def due_landmarks(self) -> list[Landmark]:
        return self._journal.due_landmarks()

    def fill_landmark(self, landmark_id: str) -> dict | None:
        lm = self._journal.get_landmark(landmark_id)
        if lm is None or lm.status == LandmarkStatus.done:
            return None

        query = lm.intention.strip()
        if lm.context.strip():
            query = f"{query} {lm.context.strip()}"
        self.ensure_narrative_context(NarrativePurpose.fill, query=query)
        lm.mark_processing()
        dice = roll_d100()
        narrative = ""
        emotion_text = ""
        emotion_intensity = 0.6
        emotion_strength = "明显触动"
        if self._narrative is not None:
            draft = self._narrative.fill_with_emotion(
                landmark=lm,
                profile_narrative=self._profile_narrative,
                continuity_memories=self._continuity_memories,
                dice=dice,
                world_background=self._world_background,
                default_intensity=0.6,
            )
            narrative = draft.narrative
            emotion_text = draft.emotion_text
            emotion_intensity = draft.emotion_intensity
            emotion_strength = draft.emotion_strength
        else:
            narrative = self._filler.fill(
                landmark=lm,
                profile_narrative=self._profile_narrative,
                continuity_memories=self._continuity_memories,
                dice=dice,
            )
        unit = self.record_story_beat(
            narrative_hint=narrative,
            salience=0.6,
            emotion_label=emotion_strength,
            action_kind=ExperienceActionKind.deciding,
            virtual_ctx=VirtualUnitContext(
                trigger=VirtualUnitTrigger.landmark,
                landmark_id=lm.id,
                dice_value=dice.value,
                dice_tendency=dice.tendency,
            ),
        )
        lm.mark_done(
            narrative=narrative,
            experience_id=unit.id,
            dice_value=dice.value,
            dice_tendency=dice.tendency,
        )
        self.save_journal()
        return {
            "hint": narrative,
            "salience": 0.6,
            "trigger": "landmark",
            "intention": lm.intention,
            "share_desire": "moderate",
            "emotion_text": emotion_text,
            "emotion_intensity": emotion_intensity,
            "emotion_strength": emotion_strength,
        }

    def tick_surprise(self, elapsed_sec: float) -> dict:
        if not self._surprise_launcher.tick(elapsed_sec=elapsed_sec):
            return {
                "triggered": False,
                "probability": round(self._surprise_launcher.probability, 3),
            }
        self.ensure_narrative_context(NarrativePurpose.surprise)
        dice = roll_d100()
        narrative = ""
        emotion_text = ""
        emotion_intensity = 0.5
        emotion_strength = "明显触动"
        if self._narrative is not None:
            draft = self._narrative.generate_with_emotion(
                dice=dice,
                continuity_memories=self._continuity_memories,
                profile_narrative=self._profile_narrative,
                world_background=self._world_background,
                default_intensity=0.5,
            )
            narrative = draft.narrative
            emotion_text = draft.emotion_text
            emotion_intensity = draft.emotion_intensity
            emotion_strength = draft.emotion_strength
        else:
            narrative = self._surprise_generator.generate(
                dice=dice,
                continuity_memories=self._continuity_memories,
                profile_narrative=self._profile_narrative,
            )
        unit = self.record_surprise(
            narrative_hint=narrative,
            dice_value=dice.value,
            dice_tendency=dice.tendency,
            salience=0.5,
        )
        return {
            "triggered": True,
            "probability": round(self._surprise_launcher.probability, 3),
            "experience_id": unit.id,
            "narrative": narrative,
            "salience": 0.5,
            "share_desire": "eager",
            "emotion_text": emotion_text,
            "emotion_intensity": emotion_intensity,
            "emotion_strength": emotion_strength,
        }

    def process_wander_experience(
        self,
        result: MemoryHeartbeatResult,
    ) -> list[dict]:
        """Wander 反刍信号 → 虚拟叙事 beat（在 LifeService 线程内执行）。"""
        beats: list[dict] = []
        portrait = self._profile_narrative
        hint = (result.signal.narrative_hint or "").strip()
        if hint:
            self.ensure_narrative_context(NarrativePurpose.fabricate, query=hint)
            portrait = self._profile_narrative
            narrative_hint = (
                f"心跳反刍线索：{hint}"
            )
            emotion_text = ""
            emotion_intensity = min(result.signal.intensity * 0.6, 0.8)
            emotion_strength = ""
            if self._narrative is not None:
                draft = self._narrative.fabricate_with_emotion(
                    hint=f"心跳反刍线索：{hint}",
                    profile_narrative=portrait,
                    continuity_memories=self._continuity_memories,
                    world_background=self._world_background,
                    default_intensity=min(result.signal.intensity * 0.6, 0.8),
                )
                narrative_hint = draft.narrative
                emotion_text = draft.emotion_text
                emotion_intensity = draft.emotion_intensity
                emotion_strength = draft.emotion_strength
            self.record_story_beat(
                narrative_hint=narrative_hint,
                salience=min(result.signal.intensity * 0.6, 0.8),
                emotion_label=emotion_strength,
                arousal_delta=result.signal.intensity * 0.15,
                virtual_ctx=VirtualUnitContext(trigger=VirtualUnitTrigger.wander),
            )
            beats.append(
                {
                    "hint": narrative_hint,
                    "salience": min(result.signal.intensity * 0.6, 0.8),
                    "trigger": "wander",
                    "share_desire": (
                        "moderate"
                        if result.signal.intensity >= 0.55
                        else "mild"
                    ),
                    "emotion_text": emotion_text,
                    "emotion_intensity": emotion_intensity,
                    "emotion_strength": emotion_strength,
                }
            )

        if result.signal.intensity >= 0.55:
            dom = result.signal.dominant_emotion or "—"
            seed = (
                f"心跳漂移节点：烈度 {result.signal.intensity:.2f}，主导情绪 {dom}"
            )
            self.ensure_narrative_context(NarrativePurpose.fabricate, query=seed)
            portrait = self._profile_narrative
            narrative_hint = (
                seed
            )
            emotion_text = ""
            emotion_intensity = result.signal.intensity
            emotion_strength = ""
            if self._narrative is not None:
                draft = self._narrative.fabricate_with_emotion(
                    hint=seed,
                    profile_narrative=portrait,
                    continuity_memories=self._continuity_memories,
                    world_background=self._world_background,
                    default_intensity=result.signal.intensity,
                )
                narrative_hint = draft.narrative
                emotion_text = draft.emotion_text
                emotion_intensity = draft.emotion_intensity
                emotion_strength = draft.emotion_strength
            self.record_story_beat(
                narrative_hint=narrative_hint,
                emotion_label=emotion_strength or dom,
                valence_delta=result.signal.intensity * -0.1,
                arousal_delta=result.signal.intensity * 0.2,
                salience=result.signal.intensity,
                action_kind=ExperienceActionKind.deciding,
                virtual_ctx=VirtualUnitContext(trigger=VirtualUnitTrigger.wander),
            )
            beats.append(
                {
                    "hint": narrative_hint,
                    "salience": result.signal.intensity,
                    "trigger": "wander_drift",
                    "share_desire": (
                        "eager"
                        if result.signal.intensity >= 0.75
                        else "moderate"
                    ),
                    "emotion_text": emotion_text,
                    "emotion_intensity": emotion_intensity,
                    "emotion_strength": emotion_strength,
                }
            )

        return beats

    def status_fragment(self) -> dict:
        return {
            "due_landmarks": len(self._journal.due_landmarks()),
            "surprise_p": round(self._surprise_launcher.probability, 3),
            "landmark_slots": self._journal.today_remaining_slots(),
        }
