from __future__ import annotations

from collections.abc import Callable

from ..domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from ..domain.virtual_codec import (
    VirtualUnitContext,
    VirtualUnitTrigger,
    stamp_virtual_context,
)
from ..unit_layer.manage.orchestrator import ExperienceOrchestrator


class ExperienceBuilder:
    """生活体验单元构造器：叙事 / 意外 → ExperienceUnit → 编排器。"""

    def __init__(self, orchestrator: ExperienceOrchestrator) -> None:
        self._orchestrator = orchestrator

    @property
    def orchestrator(self) -> ExperienceOrchestrator:
        return self._orchestrator

    def record_virtual_beat(
        self,
        narrative: str,
        *,
        perception: str = "",
        action_summary: str = "",
        emotion_text: str = "",
        emotion_label: str = "",
        valence_delta: float = 0.0,
        arousal_delta: float = 0.0,
        salience: float = 0.0,
        action_kind: ExperienceActionKind = ExperienceActionKind.reasoning,
        source: str = "narrative",
        virtual_ctx: VirtualUnitContext | None = None,
        evidence: dict | None = None,
        evidence_builder: Callable[[ExperienceUnit], dict] | None = None,
    ) -> ExperienceUnit:
        narration = narrative.strip()
        perception_text = perception.strip() or narration[:80]
        action_text = action_summary.strip() or narration[:60]
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                perception=perception_text,
                narration=narration,
            ),
            action=ExperienceAction(
                kind=action_kind,
                content=action_text,
            ),
            feeling=ExperienceFeeling(
                valence_delta=valence_delta,
                arousal_delta=arousal_delta,
                salience=salience,
                emotion_label=emotion_label or emotion_text[:24],
                salience_note=emotion_text.strip() or narration[:80],
            ),
            source=source,
        )
        if virtual_ctx is not None:
            stamp_virtual_context(unit, virtual_ctx)
        if evidence_builder is not None:
            unit.evidence = evidence_builder(unit)
        elif evidence:
            unit.evidence = dict(evidence)
        self._orchestrator.ingest(unit)
        return unit

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
        return self.record_virtual_beat(
            narrative_hint,
            emotion_label=emotion_label,
            valence_delta=valence_delta,
            arousal_delta=arousal_delta,
            salience=salience,
            action_kind=action_kind,
            source="narrative",
            virtual_ctx=virtual_ctx,
        )

    def record_surprise(
        self,
        narrative_hint: str,
        dice_value: int = 0,
        dice_tendency: str = "",
        salience: float = 0.5,
        virtual_ctx: VirtualUnitContext | None = None,
    ) -> ExperienceUnit:
        ctx = virtual_ctx or VirtualUnitContext(
            trigger=VirtualUnitTrigger.surprise,
            dice_value=dice_value,
            dice_tendency=dice_tendency,
        )
        return self.record_virtual_beat(
            narrative_hint,
            salience=salience,
            action_kind=ExperienceActionKind.attending,
            source="surprise",
            virtual_ctx=ctx,
        )

    def tick(self) -> list[ExperienceUnit]:
        return self._orchestrator.tick()
