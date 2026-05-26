from __future__ import annotations

from agent.soul.speak.compose.system.output_format import SpeakOutputFormat
from agent.soul.speak.parse import SPEAK_PARSE_FIELDS, parse_agent_output
from agent.soul.speak.protocol.tags import SPEAK_TAG_NAMES
from agent.soul.speak.stream.pipeline import SpeakStreamPipeline
from agent.soul.speak.tools.anchor import build_anchor_request


def test_speak_parse_fields():
    assert "thought" in SPEAK_PARSE_FIELDS
    assert "speak" in SPEAK_PARSE_FIELDS
    assert "session_state" in SPEAK_PARSE_FIELDS


def test_compose_output_format_uses_protocol_tags():
    prompt = SpeakOutputFormat().render_prompt()
    for tag in SPEAK_TAG_NAMES:
        assert f"[{tag}:" in prompt


def test_build_anchor_request_is_placeholder():
    req = build_anchor_request("search_knowledge")
    assert req["implemented"] is False
    assert req["tool"] == "search_knowledge"


def test_parse_core_tags_alternating():
    raw = (
        "[think:先简短想一下]"
        "[action:微笑]"
        "[speak:你好呀。]"
        "[action:点头]"
        "[speak:很高兴见到你。]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "先简短想一下"
    assert parsed.actions == ("微笑", "点头")
    assert parsed.speak == "你好呀。很高兴见到你。"
    assert parsed.session_state == "finish"
    assert len(parsed.blocks) == 6


def test_parse_optional_anchor_and_observe():
    raw = (
        "[think:查一下]"
        "[anchor:search_knowledge]"
        "[observe:外部暂无结果]"
        "[speak:我这边还没连上工具。]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.anchor_tool == "search_knowledge"
    assert parsed.observe == "外部暂无结果"
    assert parsed.speak == "我这边还没连上工具。"


def test_parse_legacy_action_prefix():
    raw = "[action:微笑] 你好呀。"
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("微笑",)
    assert parsed.speak == "你好呀。"


def test_parse_plain_text_as_speak():
    raw = "只有正文。"
    parsed = parse_agent_output(raw)
    assert parsed.speak == "只有正文。"
    assert parsed.session_state == "finish"


def test_parse_append_state():
    raw = "[speak:再说一句。][state:append]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "append"
    assert parsed.speak == "再说一句。"


def test_stream_flush_aligns_with_tags():
    raw = (
        "[think:嗯]"
        "[action:看向你]"
        "[speak:我在。]"
        "[state:finish]"
    )
    pipeline = SpeakStreamPipeline()
    events = list(pipeline.emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["thought", "action", "speak", "state", "finish"]
    assert events[-1].final is True
    assert events[-1].meta["session_state"] == "finish"


def test_stream_append_not_final():
    raw = "[speak:第一句。][state:append]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False
