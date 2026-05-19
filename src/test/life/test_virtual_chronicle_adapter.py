from __future__ import annotations

from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
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
