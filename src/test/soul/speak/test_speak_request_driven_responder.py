from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.io.outbound.stream import SpeakStreamEvent
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    ReplySegment,
    build_delivery_plan,
)
from agent.soul.speak.service import SpeakService
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound


DIRECTOR_SAMPLE = "导演样例正文不应出现"
MAIN_LLM_SPEAK = "主模型第一句。主模型第二句。"


def _role_emit(text: str) -> str:
    return (
        f"<speak context>{text}</speak context>\n"
        "<speak action>emit</speak action>"
    )


class _CapturingLLM:
    def __init__(self, reply: str | list[str]) -> None:
        self.replies = [reply] if isinstance(reply, str) else list(reply)
        self.calls: list[list] = []

    def generate_messages(self, messages):
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]

    def stream_generate_messages(self, messages):
        del messages
        raise AssertionError("request_driven responder must not stream_generate")


def _presence_mock():
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    snap.interaction.impulse_level = 0.0
    presence.snapshot.return_value = snap
    return presence


def _build_service(llm: _CapturingLLM) -> tuple[SpeakService, RecordingSpeakLifeOutbound]:
    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = _presence_mock()
    life = RecordingSpeakLifeOutbound()
    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(llm),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=life,
        life_lifecycle=None,
    )
    return service, life


def _force_director_plan(service: SpeakService, *, wait_ms: int = 0) -> None:
    plan = build_delivery_plan(
        segments=[
            ReplySegment(
                text=DIRECTOR_SAMPLE,
                wait_ms=wait_ms,
                wait_reason="fixture",
                continuity="finish",
            ),
        ],
        continuity="finish",
        sample_narration="sample",
        plan_id="fixture-plan",
        turn_index=1,
    )

    def _submit(session_id: str, user_text: str, *, turn_index: int, timeout_sec: float = 8.0):
        del user_text, timeout_sec
        state = service._state_store.session(session_id)
        state.speak_gate = "speak"
        state.pending_delivery_plan = plan
        state.delivery_plan = plan
        state.director_cache["turn_delivery"] = {
            "director": "turn_delivery",
            "payload": {"delivery_plan": plan.snapshot()},
            "reason": "fixture",
        }
        return plan

    assert service._orchestrator_thread is not None
    service._orchestrator_thread.submit_user_input_sync = _submit  # type: ignore[method-assign]


def test_request_driven_answer_comes_from_main_llm_not_director():
    llm = _CapturingLLM(_role_emit(MAIN_LLM_SPEAK))
    service, life = _build_service(llm)
    _force_director_plan(service)

    result = service.run_turn(
        "rd-1",
        "你好",
        responder="request_driven",
        stream=False,
        record=True,
    )

    assert DIRECTOR_SAMPLE not in result.answer
    assert "主模型第一句" in result.answer
    assert result.meta.get("responder") == "speak_role"
    assert "speak_role_timeline" in result.notes
    assert result.recorded is True
    assert life.recorded
    assert DIRECTOR_SAMPLE not in life.recorded[0]["agent_text"]
    director_snap = result.meta["director_delivery_plan"]
    assert isinstance(director_snap, dict)
    assert director_snap["segments"][0]["text"] == DIRECTOR_SAMPLE


def test_request_driven_success_notifies_session_social_once():
    llm = _CapturingLLM(_role_emit(MAIN_LLM_SPEAK))
    service, _life = _build_service(llm)
    _force_director_plan(service)
    service._session_manager.social.on_turn_complete = MagicMock()

    result = service.run_turn(
        "rd-social",
        "你好",
        responder="request_driven",
        stream=False,
        record=True,
    )

    assert result.recorded is True
    service._session_manager.social.on_turn_complete.assert_called_once_with(
        "rd-social",
        mode="inbound",
        session_state="finish",
        answer=result.answer,
    )


def test_request_driven_main_llm_receives_compose_bundle_context():
    marker = "WM_MARKER_REQUEST_DRIVEN_CTX"
    llm = _CapturingLLM(_role_emit("收到上下文。"))
    service, _life = _build_service(llm)
    _force_director_plan(service)

    original = service._compose_bundle

    def _compose_with_marker(session_id, user_text, *, mode="inbound", turn_index=None):
        bundle = original(
            session_id,
            user_text,
            mode=mode,
            turn_index=turn_index,
        )
        bundle.guidance.working_memory = marker
        return bundle

    service._compose_bundle = _compose_with_marker  # type: ignore[method-assign]

    result = service.run_turn(
        "rd-2",
        "在吗",
        responder="request_driven",
        stream=False,
        record=False,
    )

    assert result.answer
    assert llm.calls, "main LLM should be called"
    system_texts = [
        str(getattr(msg, "content", ""))
        for msg in llm.calls[0]
        if type(msg).__name__ == "SystemMessage"
    ]
    assert any(marker in text for text in system_texts)


def test_request_driven_stream_uses_outbound_execute(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "agent.soul.speak.io.outbound.execute.time.sleep",
        lambda *_a, **_k: None,
    )
    llm = _CapturingLLM(_role_emit(MAIN_LLM_SPEAK))
    service, _life = _build_service(llm)
    _force_director_plan(service, wait_ms=0)

    emitted: list[SpeakStreamEvent] = []
    original_emit = service._stream._emit

    def _capture(session_id: str, event: SpeakStreamEvent) -> None:
        emitted.append(event)
        original_emit(session_id, event)

    service._stream._emit = _capture  # type: ignore[method-assign]

    result = service.run_turn(
        "rd-3",
        "说两句",
        responder="request_driven",
        stream=True,
        record=False,
    )

    speak_events = [event for event in result.stream_events if event.kind == "speak"]
    assert speak_events
    speak_text = "".join(event.text for event in speak_events)
    assert DIRECTOR_SAMPLE not in speak_text
    assert "主模型第一句" in speak_text
    assert result.meta.get("stream_event_count", 0) == len(result.stream_events)
    emit_speak = [event for event in emitted if event.kind == "speak"]
    assert len(emit_speak) == len(speak_events)


def test_request_driven_role_multi_emit_segments():
    llm = _CapturingLLM(
        "<speak context>第一段。</speak context>\n"
        "<speak action>emit</speak action>\n"
        "<speak context>第二段。</speak context>\n"
        "<speak action>emit</speak action>"
    )
    service, _life = _build_service(llm)
    _force_director_plan(service)

    result = service.run_turn(
        "rd-multi",
        "继续讲",
        responder="request_driven",
        stream=False,
        record=False,
    )

    assert "第一段" in result.answer
    assert "第二段" in result.answer


def test_proactive_first_turn_survives_frameless_turn0_plan():
    from agent.soul.speak.responders.request_driven.orchestrator.director.types import (
        DirectorPlan,
    )

    llm = _CapturingLLM(_role_emit(MAIN_LLM_SPEAK))
    service, _life = _build_service(llm)
    _force_director_plan(service)

    sid = "eg-new-window"
    service.session_registry.get(sid)
    frameless = DirectorPlan(session_id=sid, target_turn_index=0, generation=0)
    service._orchestrator.compose_director.save_plan(frameless)
    loaded = service._orchestrator.compose_director.load_plan(sid, 0)
    assert loaded is not None
    assert loaded.prepared_frame is None

    result = service.run_turn(
        sid,
        "（系统：用户进入会话已约 12 秒，尚未发言。）",
        responder="request_driven",
        mode="proactive",
        stream=False,
        record=False,
    )
    assert result.bundle is not None
    assert "主模型第一句" in result.answer
