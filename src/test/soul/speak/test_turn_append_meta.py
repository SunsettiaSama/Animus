from __future__ import annotations

from agent.soul.speak.io.outbound.stream import SpeakAgentOutput, parse_agent_output
from agent.soul.speak.io.outbound.stream.pipeline import SpeakStreamPipeline
from agent.soul.speak.session.turn import _parsed_from_stream_events


def test_finish_meta_restores_append_for_turn_loop():
    raw = "[speak]line one.[/speak][state]append[/state]"
    events = list(SpeakStreamPipeline().emit_parsed_output("s", raw))
    parsed = _parsed_from_stream_events(events, parse_agent_output)
    assert parsed.session_state == "append"
    assert parsed.speak == "line one."
    # Re-parsing finish.text alone would wrongly yield finish (old bug).
    assert parse_agent_output(events[-1].text).session_state == "finish"


def test_from_finish_meta_roundtrip():
    parsed = parse_agent_output("[speak]part.[/speak][state]append[/state]")
    restored = SpeakAgentOutput.from_finish_meta(parsed.to_dict(), speak_fallback="x")
    assert restored.session_state == "append"
    assert restored.speak == "part."
