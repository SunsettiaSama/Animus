from __future__ import annotations

from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.domain.virtual_codec import (
    VirtualUnitContext,
    VirtualUnitTrigger,
    stamp_virtual_context,
)
from agent.soul.life.virtual.chronicle.adapter import virtual_entry_from_unit
from agent.soul.life.virtual.chronicle.entry import VirtualChronicleKind


def test_virtual_entry_from_narrative_unit():
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(narration="test beat"),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="test beat"),
        feeling=ExperienceFeeling(salience=0.5),
        source="narrative",
    )
    entry = virtual_entry_from_unit(unit)
    assert entry is not None
    assert entry.kind == VirtualChronicleKind.story_beat
    assert entry.summary == "test beat"


def test_virtual_entry_carries_story_refs():
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            perception="灯影晃动",
            narration="主观叙事",
        ),
        action=ExperienceAction(kind=ExperienceActionKind.deciding, content="走近灯"),
        feeling=ExperienceFeeling(salience=0.6, emotion_label="明显触动"),
        source="narrative",
    )
    stamp_virtual_context(
        unit,
        VirtualUnitContext(
            trigger=VirtualUnitTrigger.landmark,
            landmark_id="lm-1",
            dice_value=55,
            dice_tendency="大体如预期",
            story_event_id="evt-1",
            scene_id="scene-home",
            question_id="q1",
        ),
    )
    entry = virtual_entry_from_unit(unit)
    assert entry is not None
    assert entry.kind == VirtualChronicleKind.landmark
    assert entry.summary == "主观叙事"
    assert entry.story_event_id == "evt-1"
    assert entry.scene_id == "scene-home"
    assert entry.dice_value == 55
