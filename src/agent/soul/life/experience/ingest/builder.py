from __future__ import annotations

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
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                narration=narrative_hint,
            ),
            action=ExperienceAction(
                kind=action_kind,
                content=narrative_hint,
            ),
            feeling=ExperienceFeeling(
                valence_delta=valence_delta,
                arousal_delta=arousal_delta,
                salience=salience,
                emotion_label=emotion_label,
                salience_note=narrative_hint.strip(),
            ),
            source="narrative",
        )
        if virtual_ctx is not None:
            stamp_virtual_context(unit, virtual_ctx)
        self._orchestrator.ingest(unit)
        return unit

    def record_surprise(
        self,
        narrative_hint: str,
        dice_value: int = 0,
        dice_tendency: str = "",
        salience: float = 0.5,
        virtual_ctx: VirtualUnitContext | None = None,
    ) -> ExperienceUnit:
        unit = ExperienceUnit.make(
            situation=ExperienceSituation(
                narration=narrative_hint,
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.attending,
                content=narrative_hint,
            ),
            feeling=ExperienceFeeling(
                salience=salience,
                salience_note=narrative_hint.strip(),
            ),
            source="surprise",
        )
        ctx = virtual_ctx or VirtualUnitContext(
            trigger=VirtualUnitTrigger.surprise,
            dice_value=dice_value,
            dice_tendency=dice_tendency,
        )
        stamp_virtual_context(unit, ctx)
        self._orchestrator.ingest(unit)
        return unit

    def tick(self) -> list[ExperienceUnit]:
        return self._orchestrator.tick()
