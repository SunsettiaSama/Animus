from __future__ import annotations

from agent.soul.life.experience.domain.anchor_codec import AnchorUnitContext, InteractionDirection, stamp_anchor_context
from agent.soul.life.experience.domain.sources import ExperienceSource
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.io.session import DialogueCompressionBlock


def build_unit_from_compression(
    block: DialogueCompressionBlock,
    *,
    interactor_id: str = "",
) -> ExperienceUnit:
    transcript = block.transcript.strip()
    narration = block.summary.strip() or transcript
    perception = transcript or narration
    salience_note = "；".join(
        part.strip()
        for part in (block.summary, block.emotion_label, block.transcript)
        if part.strip()
    )
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id=block.session_id,
            turn_index=block.block_index + 1,
            perception=perception,
            narration=narration,
            prior_thought=f"compression_block:{block.block_index}",
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content=block.summary.strip() or narration[:120],
        ),
        feeling=ExperienceFeeling(
            salience=min(1.0, max(0.2, block.salience)),
            emotion_label=block.emotion_label.strip(),
            valence_delta=block.valence_delta,
            arousal_delta=block.arousal_delta,
            salience_note=salience_note,
        ),
        source=ExperienceSource.interaction.value,
    )
    actor = (interactor_id or block.interactor_id).strip()
    stamp_anchor_context(
        unit,
        AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id=block.session_id,
            interactor_id=actor,
        ),
    )
    return unit
