from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.speak.orchestrator.share import ShareDesireComposer
from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.io.outbound.stream import parse_agent_output
from agent.soul.speak.io.outbound.stream.flush import split_sentences
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


class _StreamLLM:
    def generate_messages(self, messages):
        return "你好，我在�?

    def stream_generate_messages(self, messages):
        for piece in ["�?, "�?, "�?, "我在�?]:
            yield piece


def test_speak_llm_engine_generate_and_stream():
    engine = SpeakLLMEngine(_StreamLLM())
    sync = engine.generate("hello", system="sys")
    assert sync.text == "你好，我在�?

    streamed = engine.generate_stream("hello", system="sys")
    assert streamed.text == "你好，我在�?
    assert streamed.chunks == ["�?, "�?, "�?, "我在�?]


def test_share_drive_detects_desire_without_threshold():
    snap = MagicMock()
    snap.state.expectation.toward_user = 0.2
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="架构进展", share_desire=ShareDesire.moderate)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.moderate
    snap.interaction.impulse_level = 0.1

    result = ShareDesireComposer(proactive_threshold=0.65).evaluate_drive(snap)
    assert result.should_speak is False
    assert "架构" in result.summary


def test_share_drive_reaches_proactive_threshold():
    snap = MagicMock()
    snap.state.expectation.toward_user = 0.7
    snap.state.expectation.to_dict.return_value = {
        "share_queue": ShareIntentQueue(
            items=[ShareIntent(topic="架构进展", share_desire=ShareDesire.eager, salience=0.8)],
        ).to_dict(),
    }
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.eager
    snap.interaction.impulse_level = 0.4

    result = ShareDesireComposer(proactive_threshold=0.65).evaluate_drive(snap)
    assert result.should_speak is True
    assert "架构" in result.summary


def test_tag_parse_and_segmenter():
    parsed = parse_agent_output("[action]微笑[/action][speak]你好呀。[/speak]")
    assert parsed.actions == ("微笑",)
    assert parsed.speak == "你好呀�?

    segments = split_sentences("第一句。第二句！第三句?", min_chars=2)
    assert len(segments) >= 2


def test_speak_service_run_turn_records_dialogue():
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    class _LLM:
        def generate_messages(self, messages):
            return "你好，我在这里�?

        def stream_generate_messages(self, messages):
            yield from "你好，我在这里�?

    soul = MagicMock()
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill

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

    from agent.soul.speak.orchestrator import SpeakOrchestrator
    from agent.soul.speak.service import SpeakService

    life_out = RecordingSpeakLifeOutbound()
    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_LLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=life_out,
        life_lifecycle=None,
    )
    result = service.run_turn("tao", "你好")
    assert result.answer
    assert result.recorded is True
    assert life_out.recorded
    assert life_out.recorded[0]["user_text"] == "你好"
