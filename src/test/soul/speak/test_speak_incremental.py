from __future__ import annotations

from agent.soul.speak.io.outbound.stream.parse.incremental import IncrementalTagStreamParser
from agent.soul.speak.io.outbound.stream.pipeline import SpeakStreamPipeline


def _collect(parser: IncrementalTagStreamParser, session_id: str, text: str):
    events = []
    for token in text:
        events.extend(parser.push(session_id, token))
    events.extend(parser.flush(session_id))
    return events


def test_incremental_announces_tag_before_speak():
    parser = IncrementalTagStreamParser()
    events = _collect(parser, "webui", "[speak]????[/speak]")
    kinds = [event.kind for event in events]
    assert kinds[0] == "tag"
    assert events[0].meta["tag"] == "speak"
    assert "speak" in kinds
    assert any(event.meta.get("phase") == "delta" for event in events if event.kind == "speak")
    assert events[-1].kind == "speak"
    assert events[-1].meta.get("phase") == "end"


def test_incremental_alternating_tags():
    raw = (
        "[think]?[/think]"
        "[action]??[/action]"
        "[speak]???[/speak]"
        "[state]finish[/state]"
    )
    parser = IncrementalTagStreamParser()
    events = _collect(parser, "webui", raw)
    tags = [event.meta.get("tag") for event in events if event.kind == "tag"]
    assert tags == ["action", "speak", "state"]
    assert not any(event.kind == "thought" for event in events)
    assert any(event.kind == "action" and event.meta.get("phase") == "end" for event in events)
    assert any(event.kind == "state" for event in events)


def test_incremental_xml_bracket_tags():
    raw = (
        "[action]????????[/action]"
        "[speak]??????????[/speak]"
        "[state]finish[/state]"
    )
    parser = IncrementalTagStreamParser()
    events = _collect(parser, "webui", raw)
    tags = [event.meta.get("tag") for event in events if event.kind == "tag"]
    assert tags == ["action", "speak", "state"]
    action_text = "".join(event.text or "" for event in events if event.kind == "action")
    speak_text = "".join(event.text or "" for event in events if event.kind == "speak")
    assert "???" in action_text
    assert "??????" in speak_text


def test_stream_generate_incremental_pipeline():
    class _FakeEngine:
        def stream(self, user_text, *, system="", context=""):
            raw = (
                "[think]???[/think]"
                "[speak]????[/speak]"
                "[speak]????[/speak]"
                "[state]finish[/state]"
            )
            yield from raw

    pipeline = SpeakStreamPipeline(flush_mode="segment")
    events = list(
        pipeline.stream_generate(_FakeEngine(), "webui", "hello", system="sys")
    )
    assert events[0].kind == "tag"
    assert events[-1].kind == "finish"
    tag_events = [event for event in events if event.kind == "tag"]
    assert len(tag_events) >= 2
    speak_end = [event for event in events if event.kind == "speak" and event.meta.get("phase") == "end"]
    assert len(speak_end) >= 2
