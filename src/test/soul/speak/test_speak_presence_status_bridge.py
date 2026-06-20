from __future__ import annotations

import time
from unittest.mock import MagicMock

from agent.soul.presence import PresenceService
from agent.soul.presence.state.lingering import RecentExperiencePortrait
from agent.soul.speak.io.inbound.compose import (
    SpeakStatusStore,
    apply_presence_status_update,
    collect_status_injected,
)
from agent.soul.speak.service import SpeakService


def _wait_ready_frame(speak: SpeakService, session_id: str = "tao", *, timeout: float = 1.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        frame = speak.compose_runner.take_ready_frame(session_id)
        if frame is not None:
            return frame
        time.sleep(0.01)
    return None


def _snap_with_portrait(session_id: str, narrative: str):
    snap = MagicMock()
    snap.session_id = session_id
    snap.state.recent_portrait = RecentExperiencePortrait(narrative=narrative)
    return snap


def test_presence_emits_status_update_on_persist():
    updates: list[str] = []
    presence = PresenceService()
    presence.register_status_update_listener(
        lambda snap: updates.append(snap.state.recent_portrait.narrative),
    )

    session = presence._session("tao")
    session.state.recent_portrait = RecentExperiencePortrait(narrative="\u4f60\u6709\u70b9\u671f\u5f85")
    presence._persist("tao")

    assert updates == ["\u4f60\u6709\u70b9\u671f\u5f85"]


def _speak_with_mock_life(**kwargs) -> SpeakService:
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    kwargs.setdefault("presence", PresenceService())
    kwargs.setdefault("persona", MagicMock())
    return SpeakService(life_outbound=RecordingSpeakLifeOutbound(), **kwargs)


def test_speak_on_presence_status_update_writes_status_store():
    store = SpeakStatusStore()
    speak = _speak_with_mock_life()
    speak._inbound_compose._store = store

    snap = _snap_with_portrait("tao", "\u4f60\u6b64\u523b\u5e73\u9759")

    speak.on_presence_status_update(snap)

    assert store.presence("tao") == "\u4f60\u6b64\u523b\u5e73\u9759"
    assert "\u60c5\u611f\uff1a" not in store.presence("tao")


def test_collect_status_prefers_store_over_snapshot():
    store = SpeakStatusStore()
    store.update_presence("tao", "\u4f60\u5e26\u7740\u7f13\u5b58\u91cc\u7684\u8fd1\u671f\u7ecf\u5386")

    snap = MagicMock()
    snap.session_id = "tao"
    snap.state.recent_portrait = RecentExperiencePortrait(
        narrative="\u4f60\u5b9e\u65f6\u72b6\u6001",
    )

    injected = collect_status_injected(
        presence_snap=snap,
        status_store=store,
    )

    assert injected.presence == "\u4f60\u5e26\u7740\u7f13\u5b58\u91cc\u7684\u8fd1\u671f\u7ecf\u5386"
    assert "\u4f60\u5b9e\u65f6\u72b6\u6001" not in injected.presence


def test_apply_presence_status_update_renders_snapshot():
    store = SpeakStatusStore()
    snap = _snap_with_portrait("tao", "\u4f60\u4e13\u6ce8\u5728\u5bf9\u8bdd\u4e0a")

    apply_presence_status_update(store, snap)

    assert store.presence("tao") == "\u4f60\u4e13\u6ce8\u5728\u5bf9\u8bdd\u4e0a"


def test_soul_presence_status_update_reaches_speak():
    presence = PresenceService()
    speak = _speak_with_mock_life(presence=presence)
    updates: list[str] = []

    def _capture(snap) -> None:
        speak.on_presence_status_update(snap)
        updates.append(speak.inbound_compose.status_store.presence(snap.session_id))

    presence.register_status_update_listener(_capture)

    session = presence._session("tao")
    narrative = "\u4f60\u611f\u5230\u94fe\u8def\u901a\u7545"
    session.state.recent_portrait = RecentExperiencePortrait(narrative=narrative)
    presence._persist("tao")

    assert updates
    assert narrative in updates[-1]
    assert speak.inbound_compose.status_store.presence("tao") == narrative


def test_status_update_refreshes_compose_prefetch_frame():
    persona = MagicMock()
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

    persona.get_persona_snapshot.return_value = persona_snapshot_with_distill(
        name="\u8389\u5948\u5a05",
    )
    presence = PresenceService()
    speak = _speak_with_mock_life(presence=presence, persona=persona)
    presence.register_status_update_listener(speak.on_presence_status_update)

    speak.start()
    old_narr = "\u4f60\u65e7\u72b6\u6001"
    old = presence._session("tao")
    old.state.recent_portrait = RecentExperiencePortrait(narrative=old_narr)
    presence._persist("tao")
    first = _wait_ready_frame(speak)
    assert first is not None
    assert old_narr in first.status.presence

    new_narr = "\u4f60\u65b0\u72b6\u6001"
    new = presence._session("tao")
    new.state.recent_portrait = RecentExperiencePortrait(narrative=new_narr)
    presence._persist("tao")
    second = _wait_ready_frame(speak)
    assert second is not None
    assert new_narr in second.status.presence
    assert old_narr not in second.status.presence

    bundle = speak.orchestrator.finalize(second, "\u4f60\u597d")
    system = bundle.build_system()
    assert new_narr in system
    forbidden_header = "\u3010\u5f53\u4e0b\u6001\u00b7\u72b6\u6001\u3011"
    assert forbidden_header not in system
    assert bundle.meta["compose_source"] == "prefetch"

    speak.stop()
