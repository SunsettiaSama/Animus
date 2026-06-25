from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.soul.handlers.api.actions import SpeakAction
from agent.soul.request import SoulDomain, SoulRequest
from agent.soul.speak.io.handler import SpeakHandler


def test_speak_handler_api_property(soul_service):
    assert not soul_service.speak_initialized
    soul_service.start()
    handler = soul_service.speak
    service = handler.api
    assert service is soul_service.speak.api
    assert soul_service.speak_initialized
    soul_service.stop()
    assert soul_service.state == "stopped"


def test_record_dialogue_turn_matches_dispatch(soul_service):
    soul_service.start()
    via_method = soul_service.record_dialogue_turn(
        "\u4f60\u597d",
        "\u5728",
        session_id="tao",
    )
    via_dispatch = soul_service.dispatch(SoulRequest(
        domain=SoulDomain.speak,
        action=SpeakAction.RECORD_DIALOGUE,
        payload={
            "session_id": "tao2",
            "question": "\u804a\u804a",
            "answer": "\u597d\u7684",
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
    assert opened["ok"] is True
    assert opened["session_id"] == "webui"
    assert opened["turn_count"] == 0

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
    assert closed["session_id"] == "webui"
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

    with pytest.raises(RuntimeError, match="\u672a\u8fd0\u884c"):
        soul_service.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.RECORD_DIALOGUE,
            payload={"session_id": "tao", "question": "q", "answer": "a"},
        ))


def test_speak_run_turn_requires_running(soul_service):
    with pytest.raises(RuntimeError, match="\u672a\u8fd0\u884c"):
        soul_service.speak_run_turn("tao", "hi")


def test_speak_submit_user_input_requires_running(soul_service):
    with pytest.raises(RuntimeError, match="\u672a\u8fd0\u884c"):
        soul_service.speak_submit_user_input("tao", "hi")


def test_speak_handler_run_turn_passes_pipeline():
    calls: list[dict[str, object]] = []

    class _FakeSpeakService:
        def run_turn(self, session_id, text, *, stream=False, mode="inbound", pipeline=None):
            calls.append({
                "session_id": session_id,
                "text": text,
                "stream": stream,
                "mode": mode,
                "pipeline": pipeline,
            })
            return SimpleNamespace(
                session_id=session_id,
                answer="ok",
                output=None,
                meta={"session_state": "finish", "pipeline": pipeline},
                recorded=False,
                bundle=SimpleNamespace(summary_for_log=lambda: {}),
                stream_events=[],
                notes=[],
            )

    handler = SpeakHandler(
        get_speak_service=lambda: _FakeSpeakService(),
        experience=SimpleNamespace(),
    )

    result = handler.handle(
        SpeakAction.RUN_TURN,
        {
            "session_id": "s1",
            "text": "hello",
            "stream": True,
            "mode": "inbound",
            "pipeline": "request_driven",
        },
    )

    assert calls == [{
        "session_id": "s1",
        "text": "hello",
        "stream": True,
        "mode": "inbound",
        "pipeline": "request_driven",
    }]
    assert result["pipeline"] == "request_driven"
