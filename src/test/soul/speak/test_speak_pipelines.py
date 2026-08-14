from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.soul.speak.responders import SpeakResponderRouter, normalize_speak_responder
from agent.soul.speak.responders.request_driven.orchestrator import SpeakPromptBundle
from agent.soul.speak.session.queue import SessionQueueHub, UserInputItem


def test_normalize_speak_responder_defaults_to_request_driven():
    assert normalize_speak_responder(None) == "request_driven"
    assert normalize_speak_responder("") == "request_driven"


def test_normalize_speak_responder_accepts_request_driven():
    assert normalize_speak_responder("request_driven") == "request_driven"


def test_normalize_speak_responder_accepts_rhythm():
    assert normalize_speak_responder("rhythm") == "rhythm"


def test_normalize_speak_responder_rejects_unknown_value():
    with pytest.raises(ValueError, match="unknown speak responder"):
        normalize_speak_responder("classic")


def test_responder_router_dispatches_by_user_input_item_responder():
    called: list[str] = []

    class _Runner:
        def __init__(self, name: str) -> None:
            self._name = name

        def run(self, item):
            called.append(self._name)
            return item.responder

    router = SpeakResponderRouter(
        legacy_qa=_Runner("legacy"),
        request_driven=_Runner("request"),
        rhythm=_Runner("rhythm"),
    )

    assert router.run(UserInputItem("s1", "hello", responder="legacy_qa")) == "legacy_qa"
    assert router.run(UserInputItem("s1", "hello", responder="request_driven")) == "request_driven"
    assert router.run(UserInputItem("s1", "hello", responder="rhythm")) == "rhythm"
    assert called == ["legacy", "request", "rhythm"]


def test_session_queue_preserves_responder_for_pending_user_input():
    hub = SessionQueueHub()
    hub.begin_push("s1", "old question")

    hub.submit_user_input(
        "s1",
        "new question",
        stream=True,
        mode="inbound",
        record=True,
        responder="request_driven",
    )

    item = hub.pop_pending_user_input("s1")
    assert item is not None
    assert item.responder == "request_driven"
    assert item.user_text == "new question"


def test_speak_service_routes_rhythm_and_rejects_unknown_responder():
    from agent.soul.presence.share_desire import ShareDesire
    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from agent.soul.speak.service import SpeakService, SpeakTurnResult
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    class _LLM:
        def generate_messages(self, messages):
            del messages
            return "[speak]hi[/speak][state]finish[/state]"

        def stream_generate_messages(self, messages):
            del messages
            yield "[speak]hi[/speak][state]finish[/state]"

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
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

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_LLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )

    routed: list[str] = []

    def _fake_rhythm_run(item):
        routed.append(item.responder)
        return SpeakTurnResult(
            session_id=item.session_id,
            answer="",
            bundle=SpeakPromptBundle(session_id=item.session_id, mode=item.mode),
            recorded=False,
            notes=["rhythm_pipeline", "rhythm_no_speak"],
            meta={"responder": "rhythm", "gate": "listen"},
        )

    service._rhythm_runner.run = _fake_rhythm_run  # type: ignore[method-assign]
    result = service.run_turn("s1", "hello", responder="rhythm")
    assert routed == ["rhythm"]
    assert result.meta["responder"] == "rhythm"
    assert "rhythm_pipeline" in result.notes

    with pytest.raises(ValueError, match="unknown speak responder"):
        service.run_turn("s1", "hello", responder="classic")
