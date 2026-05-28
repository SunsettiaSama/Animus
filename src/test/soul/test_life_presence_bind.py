from __future__ import annotations

from agent.soul.life.experience.stack import LifeExperienceStack
from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.presence import PresenceService
from agent.soul.presence.share_desire import StaticStatePatch


def test_life_presence_bind_syncs_after_unit_ingest(tmp_path):
    presence = PresenceService(life_dir=str(tmp_path))
    stack = LifeExperienceStack(life_dir=str(tmp_path))
    stack.bind_presence(presence)

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="tao",
            perception="窗外有风",
            narration="注意到环境变�?,
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.attending,
            content="注意到环境变�?,
        ),
        feeling=ExperienceFeeling(
            salience=0.5,
            emotion_label="平静",
        ),
        source="narrative",
    )
    stack.orchestrator.ingest(unit)

    snap = presence.snapshot("tao")
    assert "环境变化" in snap.state.cognition.thinking or "窗外" in snap.state.perception.narrative


def test_presence_sync_from_life_via_bound_stack(tmp_path):
    presence = PresenceService(life_dir=str(tmp_path))
    stack = LifeExperienceStack(life_dir=str(tmp_path))
    stack.bind_presence(presence)

    presence.patch_static("tao", StaticStatePatch(affect="初始"))
    stack.orchestrator.ingest(
        ExperienceUnit.make(
            situation=ExperienceSituation(
                session_id="tao",
                narration="新的叙事",
            ),
            action=ExperienceAction(
                kind=ExperienceActionKind.attending,
                content="新的叙事",
            ),
            feeling=ExperienceFeeling(salience=0.6, emotion_label="专注"),
            source="surprise",
        )
    )

    result = presence.sync_from_life("tao")
    assert result["applied"] is True
    assert "新的叙事" in presence.snapshot("tao").state.cognition.thinking
