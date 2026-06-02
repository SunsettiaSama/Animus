from __future__ import annotations

from agent.soul.presence import PresenceService
from agent.soul.presence.share_desire import StaticStatePatch
from agent.soul.presence.state.lingering import LingeringMood, RecentExperiencePortrait
from agent.soul.presence.state.presence_state import PresenceState


def test_presence_state_serializes_lingering_and_portrait():
    state = PresenceState()
    state.lingering_moods = [
        LingeringMood(text="你会有点累", until_iso="2099-01-01T00:00:00+00:00"),
    ]
    state.recent_portrait = RecentExperiencePortrait(
        narrative="你这两天在雨里走过。",
        distilled_at="2026-06-01T12:00:00+00:00",
        source_unit_ids=["u1"],
    )
    restored = PresenceState.from_dict(state.to_dict())
    assert restored.lingering_moods[0].text == "你会有点累"
    assert restored.recent_portrait.narrative.startswith("你这两天")


def test_presence_service_persist_roundtrip(tmp_path):
    svc = PresenceService(life_dir=str(tmp_path))
    svc.patch_static("tao", StaticStatePatch(affect="内部用"))
    session = svc._session("tao")
    session.state.recent_portrait = RecentExperiencePortrait(
        narrative="你最近记下了雨中的那段路。",
    )
    svc._persist("tao")

    svc2 = PresenceService(life_dir=str(tmp_path))
    snap = svc2.snapshot("tao")
    assert snap.state.recent_portrait.narrative.startswith("你最近")
