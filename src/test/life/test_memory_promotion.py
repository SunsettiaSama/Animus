from __future__ import annotations

from agent.soul.life.experience.unit_layer.promote.policy import should_promote_to_memory
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)


def _unit(
    *,
    salience_note: str = "",
    narration: str = "",
    promote_to_memory: bool = False,
    annotation_decided: bool = True,
    impression_intensity: float = 0.0,
    impression_why: str = "",
) -> ExperienceUnit:
    return ExperienceUnit.make(
        situation=ExperienceSituation(narration=narration),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content=""),
        feeling=ExperienceFeeling(
            salience_note=salience_note,
            promote_to_memory=promote_to_memory,
            annotation_decided=annotation_decided,
            impression_intensity=impression_intensity,
            impression_why=impression_why or salience_note,
        ),
        source="interaction",
    )


def test_promote_requires_explicit_intent():
    assert should_promote_to_memory(
        _unit(
            salience_note="这轮对我很重要，印象深刻",
            promote_to_memory=True,
            impression_intensity=0.8,
            impression_why="印象深刻",
        )
    )


def test_no_promote_without_intent():
    assert not should_promote_to_memory(
        _unit(salience_note="这轮对我很重要，印象深刻", promote_to_memory=False)
    )


def test_undecided_does_not_promote():
    assert not should_promote_to_memory(
        _unit(annotation_decided=False, promote_to_memory=True)
    )


def test_is_salient_delegates_to_promote_intent():
    unit = _unit(promote_to_memory=True, impression_why="难忘的一次对话")
    assert unit.is_salient(0.5) is True
    assert unit.is_salient() is True
    assert _unit(promote_to_memory=False).is_salient() is False
