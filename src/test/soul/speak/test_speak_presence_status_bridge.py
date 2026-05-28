from __future__ import annotations

import time
from unittest.mock import MagicMock

from agent.soul.presence import PresenceService
from agent.soul.presence.share_desire import StaticStatePatch
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


def test_presence_emits_status_update_on_persist():
    updates: list[str] = []
    presence = PresenceService()
    presence.register_status_update_listener(
        lambda snap: updates.append(snap.state.affect.narrative),
    )

    presence.patch_static("tao", StaticStatePatch(affect="有点期待"))

    assert updates == ["有点期待"]


def test_speak_on_presence_status_update_writes_status_store():
    store = SpeakStatusStore()
    speak = SpeakService(presence=None)
    speak._inbound_compose._store = store

    snap = MagicMock()
    snap.session_id = "tao"
    snap.state.affect.render.return_value = "平静"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""

    speak.on_presence_status_update(snap)

    assert "平静" in store.presence("tao")


def test_collect_status_prefers_store_over_snapshot():
    store = SpeakStatusStore()
    store.update_presence("tao", "【当下态·状态】\n情感：缓存�?)

    snap = MagicMock()
    snap.session_id = "tao"
    snap.state.affect.render.return_value = "实时�?

    injected = collect_status_injected(
        presence_snap=snap,
        status_store=store,
    )

    assert injected.presence == "【当下态·状态】\n情感：缓存�?
    assert "实时�? not in injected.presence


def test_apply_presence_status_update_renders_snapshot():
    store = SpeakStatusStore()
    snap = MagicMock()
    snap.session_id = "tao"
    snap.state.affect.render.return_value = "专注"
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""

    apply_presence_status_update(store, snap)

    assert "专注" in store.presence("tao")


def test_soul_presence_status_update_reaches_speak():
    presence = PresenceService()
    speak = SpeakService(presence=presence)
    updates: list[str] = []

    def _capture(snap) -> None:
        speak.on_presence_status_update(snap)
        updates.append(speak.inbound_compose.status_store.presence(snap.session_id))

    presence.register_status_update_listener(_capture)

    presence.patch_static("tao", StaticStatePatch(affect="链路通畅"))

    assert updates
    assert "链路通畅" in updates[-1]
    assert "链路通畅" in speak.inbound_compose.status_store.presence("tao")


def test_status_update_refreshes_compose_prefetch_frame():
    persona = MagicMock()
    persona.get_persona_snapshot.return_value = {
        "profile": {"name": "小A"},
        "self_concept": {},
    }
    presence = PresenceService()
    speak = SpeakService(presence=presence, persona=persona)
    presence.register_status_update_listener(speak.on_presence_status_update)

    speak.start()
    presence.patch_static("tao", StaticStatePatch(affect="旧状�?))
    first = _wait_ready_frame(speak)
    assert first is not None
    assert "旧状�? in first.status.presence

    presence.patch_static("tao", StaticStatePatch(affect="新状�?))
    second = _wait_ready_frame(speak)
    assert second is not None
    assert "新状�? in second.status.presence
    assert "旧状�? not in second.status.presence

    bundle = speak.composer.finalize(second, "你好")
    system = bundle.build_system()
    assert "新状�? in system
    assert bundle.meta["compose_source"] == "prefetch"

    speak.stop()
