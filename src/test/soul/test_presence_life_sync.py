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


def test_life_bundle_merges_static_without_auto_share(tmp_path):
    log = ExperienceLog(str(tmp_path))
    u1 = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="虚拟季节节拍"),
        action=ExperienceAction(kind=ExperienceActionKind.reasoning, content="虚拟季节节拍"),
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
    # merge 不再折叠分享意图
    assert bundle.enqueue_share is False
    assert bundle.wants_to_share is False


def test_sync_life_bundle_respects_annotation_and_channel(tmp_path):
    svc = PresenceService(life_dir=str(tmp_path))
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id="tao",
            channel_id="chan-1",
            narration="想分享一件事",
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content="想分享一件事",
        ),
        feeling=ExperienceFeeling(
            salience=0.55,
            emotion_label="期待",
            enqueue_share=True,
            push_to_user=True,
            share_content="想分享一件事：晨光里的虹彩",
            share_why="值得告诉访客",
            annotation_decided=True,
            promote_to_memory=True,
            impression_intensity=0.7,
            impression_why="触动明显",
        ),
        source="narrative",
    )
    bundle = presence_bundle_from_unit(unit)
    assert bundle.enqueue_share is True
    assert bundle.channel_id == "chan-1"
    sync = svc.sync_life_bundle(bundle)
    assert sync["notes"]
    # 分享落在 channel session，而非仅靠 salience
    assert svc.share_queue_size("chan-1") >= 1
    snap = svc.snapshot("chan-1")
    assert snap.state.expectation.pending_push is True


def test_no_annotation_does_not_enqueue():
    svc = PresenceService()
    unit = ExperienceUnit.make(
        situation=ExperienceSituation(session_id="tao", narration="普通路过"),
        action=ExperienceAction(kind=ExperienceActionKind.attending, content="普通路过"),
        feeling=ExperienceFeeling(salience=0.9, annotation_decided=False),
        source="narrative",
    )
    bundle = presence_bundle_from_unit(unit)
    assert bundle.enqueue_share is False
    svc.sync_life_bundle(bundle)
    assert svc.share_queue_size("tao") == 0


def test_state_block_routes_through_life_sync(tmp_path):
    svc = PresenceService(life_dir=str(tmp_path))
    notes = svc.apply_state_block(
        PresenceStateBlock.rumination(
            narratives={"thinking": "回想旧对话"},
            meta={
                "enqueue_share": "true",
                "push_to_user": "true",
                "share_content": "想聊聊刚才的事",
                "share_desire": "mild",
                "target_channel_id": "web-chan",
                "promote_to_memory": "true",
            },
        ),
    )
    assert notes
    assert svc.share_queue_size("web-chan") == 1
