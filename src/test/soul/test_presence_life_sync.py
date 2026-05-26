from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import presence_bundle_from_unit
from agent.soul.life.experience.log import ExperienceLog
from agent.soul.life.experience.presence_supply import supply_presence_bundle_from_life
from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.presence import PresenceService
from agent.soul.presence.state_block import PresenceStateBlock


def test_life_bundle_merges_hot_units(tmp_path):
    log = ExperienceLog(str(tmp_path))
    u1 = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="虚拟叙事节拍"),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="虚拟叙事节拍"),
        feeling=ExperienceFeeling(salience=0.6, emotion_label="好奇"),
        source="narrative",
    )
    u2 = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="意外惊喜"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="意外惊喜"),
        feeling=ExperienceFeeling(salience=0.5),
        source="surprise",
    )
    log.append(u1)
    log.append(u2)
    bundle = supply_presence_bundle_from_life(log, "tao", hours=24)
    assert bundle is not None
    assert "虚拟叙事" in bundle.narration or "意外" in bundle.narration
    assert bundle.wants_to_share is True


def test_sync_life_bundle_updates_static_not_boundary_fsm():
    svc = PresenceService()
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="想分享一件事"),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content="想分享一件事"),
        feeling=ExperienceFeeling(salience=0.55, emotion_label="期待"),
        source="narrative",
    )
    bundle = presence_bundle_from_unit(unit)
    sync = svc.sync_life_bundle(bundle)
    snap = svc.snapshot("tao")
    assert "期待" in snap.state.affect.narrative or "想分享" in snap.state.cognition.thinking
    assert snap.expectation.value == "none"
    assert "static:" in " ".join(sync["static_notes"])
    assert svc.share_queue_size("tao") >= 1


def test_state_block_routes_through_life_sync():
    svc = PresenceService()
    notes = svc.apply_state_block(PresenceStateBlock.rumination(
        narratives={"thinking": "回忆起旧对话"},
        meta={"wants_to_share": "true", "share_topic": "想聊聊刚才的事", "share_desire": "mild"},
    ))
    assert notes
    assert svc.share_queue_size("tao") == 1
