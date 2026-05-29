from __future__ import annotations

from agent.soul.life.experience.memory_promotion import (
    matches_demote_narration,
    matches_promote_narration,
    should_promote_to_memory,
)
from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)


def _unit(*, salience_note: str = "", narration: str = "") -> ExperienceUnit:
    return ExperienceUnit.make(
        situation=ExperienceSituation(narration=narration),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content=""),
        feeling=ExperienceFeeling(salience_note=salience_note),
        source="interaction",
    )


def test_promote_from_salience_note():
    assert should_promote_to_memory(_unit(salience_note="这轮对我很重要，印象深刻"))
    assert matches_promote_narration("路边突然下雨，出乎意料")


def test_demote_blocks_promote():
    unit = _unit(salience_note="只是日常寒暄，不太重要")
    assert matches_demote_narration("只是日常寒暄")
    assert not should_promote_to_memory(unit)


def test_neutral_without_match_does_not_promote():
    assert not should_promote_to_memory(_unit(salience_note="聊了聊天气和出行"))
    assert not should_promote_to_memory(_unit())


def test_is_salient_delegates_to_regex():
    unit = _unit(salience_note="难忘的一次对话")
    assert unit.is_salient(0.5) is True
    assert unit.is_salient() is True
