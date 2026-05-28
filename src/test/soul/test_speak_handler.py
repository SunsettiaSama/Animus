from __future__ import annotations

from agent.soul.handlers.api.actions import SpeakAction
from agent.soul.request import SoulDomain, SoulRequest


def test_speak_handler_api_property(soul_service):
    soul_service.start()
    handler = soul_service.speak
    service = handler.api
    assert service is soul_service.speak.api
    soul_service.stop()


def test_record_dialogue_turn_matches_dispatch(soul_service):
    soul_service.start()
    via_method = soul_service.record_dialogue_turn("你好", "�?, session_id="tao")
    via_dispatch = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.RECORD_DIALOGUE,
        payload={
            "session_id": "tao2",
            "question": "聊聊",
            "answer": "好的",
        },
    ))
    assert via_method["ok"] is True
    assert via_method["session_id"] == "tao"
    assert via_dispatch["ok"] is True
    assert via_dispatch["session_id"] == "tao2"
    soul_service.stop()


def test_start_and_close_dialogue_session_via_dispatch(soul_service):
    soul_service.start()
    opened = soul_service.start_dialogue_session("webui")
    assert opened == {"ok": True, "session_id": "webui", "turn_count": 0}

    soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.RECORD_DIALOGUE,
        payload={
            "session_id": "webui",
            "question": "q",
            "answer": "a",
        },
    ))
    state = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.DIALOGUE_STATE,
        payload={"session_id": "webui"},
    ))
    assert state["open"] is True
    assert state["turn_count"] == 1

    closed = soul_service.close_dialogue_interaction("webui")
    assert closed["ok"] is True
    assert closed["ingested"] is True
    assert closed["turn_index"] == 1
    soul_service.stop()


def test_speak_read_actions_allowed_in_idle(soul_service):
    snap = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.DRIVE_SNAPSHOT,
        payload={"session_id": "tao"},
    ))
    assert snap["session_id"] == "tao"

    state = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.DIALOGUE_STATE,
        payload={"session_id": "tao"},
    ))
    assert state["open"] is False

    import pytest

    with pytest.raises(RuntimeError, match="未运�?):
        soul_service.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.RECORD_DIALOGUE,
            payload={"session_id": "tao", "question": "q", "answer": "a"},
        ))
