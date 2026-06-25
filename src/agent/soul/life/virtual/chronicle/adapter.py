from __future__ import annotations

from ...experience.domain.unit import ExperienceUnit
from ...experience.domain.virtual_codec import VirtualUnitTrigger, read_virtual_context
from .entry import VirtualChronicleEntry, VirtualChronicleKind


def virtual_entry_from_unit(unit: ExperienceUnit) -> VirtualChronicleEntry | None:
    """ExperienceUnit → VirtualChronicleEntry（仅虚拟 source）。"""
    ctx = read_virtual_context(unit)
    hint = unit.situation.narration or unit.situation.perception or unit.action.content

    if unit.source == "surprise":
        kind = VirtualChronicleKind.surprise
        trigger = VirtualUnitTrigger.surprise.value
    elif unit.source == "narrative":
        trigger = ctx.trigger.value if ctx else VirtualUnitTrigger.fabricate.value
        if trigger in (
            VirtualUnitTrigger.landmark.value,
            VirtualUnitTrigger.landmark_plan.value,
        ):
            kind = VirtualChronicleKind.landmark
        elif trigger == VirtualUnitTrigger.wander.value:
            kind = VirtualChronicleKind.wander_beat
        else:
            kind = VirtualChronicleKind.story_beat
    elif unit.source == "collision":
        kind = VirtualChronicleKind.collision
        trigger = "collision"
    else:
        return None

    return VirtualChronicleEntry(
        kind=kind,
        summary=hint[:120],
        experience_id=unit.id,
        trigger=trigger,
        landmark_id=ctx.landmark_id if ctx else "",
        dice_value=ctx.dice_value if ctx else 0,
        dice_tendency=ctx.dice_tendency if ctx else "",
        emotion_label=unit.feeling.emotion_label,
        salience=unit.feeling.salience,
        story_event_id=ctx.story_event_id if ctx else "",
        scene_id=ctx.scene_id if ctx else "",
    )


def collision_entry_from_unit(
    unit: ExperienceUnit,
    merged_text: str,
    *,
    virtual_only: bool,
) -> VirtualChronicleEntry:
    return VirtualChronicleEntry(
        kind=VirtualChronicleKind.collision,
        summary=merged_text[:120],
        experience_id=unit.id,
        trigger="collision",
        emotion_label=unit.feeling.emotion_label,
        salience=unit.feeling.salience,
    )
