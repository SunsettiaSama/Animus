from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import presence_bundle_from_unit
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog
from agent.soul.life.experience.ingest.presence import supply_presence_bundle_from_life
from agent.soul.life.experience.domain.unit import (
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
        situation=ExperienceSituation(session_id="tao", narration="\u865a\u62df\u5b63\u4e8b\u8282\u62cd"),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="\u865a\u62df\u5b63\u4e8b\u8282\u62cd"),
        feeling=ExperienceFeeling(salience=0.6, emotion_label="\u597d\u5947"),
        source="narrative",
    )
    u2 = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="\u610f\u5916\u60ca\u559c"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="\u610f\u5916\u60ca\u559c"),
        feeling=ExperienceFeeling(salience=0.5),
        source="surprise",
    )
    log.append(u1)
    log.append(u2)
    bundle = supply_presence_bundle_from_life(log, "tao", hours=24)
    assert bundle is not None
    assert bundle.wants_to_share is True


def test_sync_life_bundle_updates_static_not_boundary_fsm():
    svc = PresenceService()
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="tao",
            narration="\u60f3\u5206\u4eab\u4e00\u4ef6\u4e8b",
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content="\u60f3\u5206\u4eab\u4e00\u4ef6\u4e8b",
        ),
        feeling=ExperienceFeeling(salience=0.55, emotion_label="\u671f\u5f85"),
        source="narrative",
    )
    bundle = presence_bundle_from_unit(unit)
    sync = svc.sync_life_bundle(bundle)
    snap = svc.snapshot("tao")
    mood_texts = [m.text for m in snap.state.lingering_moods]
    assert any("\u671f\u5f85" in t for t in mood_texts) or "\u60f3\u5206\u4eab" in (
        snap.state.cognition.thinking or ""
    )
    assert snap.expectation.value == "none"
    assert "static:" in " ".join(sync["static_notes"])
    assert svc.share_queue_size("tao") >= 1


def test_state_block_routes_through_life_sync():
    svc = PresenceService()
    notes = svc.apply_state_block(
        PresenceStateBlock.rumination(
            narratives={"thinking": "\u56de\u60f3\u8d77\u65e7\u5bf9\u8bdd"},
            meta={
                "wants_to_share": "true",
                "share_topic": "\u60f3\u804a\u804a\u521a\u624d\u7684\u4e8b",
                "share_desire": "mild",
            },
        ),
    )
    assert notes
    assert svc.share_queue_size("tao") == 1
