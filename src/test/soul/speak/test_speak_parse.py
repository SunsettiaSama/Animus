from __future__ import annotations

from agent.soul.speak.pipelines.request_driven.orchestrator.system.output_format import SpeakOutputFormat
from agent.soul.speak.io.outbound.stream import SPEAK_PARSE_FIELDS, SpeakAgentOutput, parse_agent_output
from agent.soul.speak.io.outbound.stream.pipeline import SpeakStreamPipeline
from agent.soul.speak.tools.anchor import build_anchor_request


def test_speak_parse_fields():
    assert "thought" in SPEAK_PARSE_FIELDS
    assert "speak" in SPEAK_PARSE_FIELDS
    assert "session_state" in SPEAK_PARSE_FIELDS


def test_compose_output_format_uses_protocol_tags():
    prompt = SpeakOutputFormat().render_prompt()
    for tag in ("think", "speak", "action", "state"):
        assert f"[{tag}]" in prompt and f"[/{tag}]" in prompt
    assert "[anchor:" not in prompt
    assert "????? not in prompt
    assert "[observe:" not in prompt
    assert "不?每轮??须说? in prompt
    assert "share" in prompt
    assert "?? in prompt


def test_build_anchor_request_disabled_until_tool_layer():
    req = build_anchor_request("search_knowledge")
    assert req["implemented"] is False
    assert req["tool"] == "search_knowledge"
    assert "工???? in req["reason"]


def test_parse_core_tags_alternating():
    raw = (
        "[think:???????]"
        "[action:微?]"
        "[speak:你好????]"
        "[action:?头]"
        "[speak:???见?你??]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "???????
    assert parsed.actions == ("微?", "?头")
    assert parsed.speak == "你好???????见?你??
    assert parsed.session_state == "finish"
    assert len(parsed.blocks) == 6


def test_parse_optional_anchor_and_observe():
    raw = (
        "[think:???]"
        "[anchor:search_knowledge]"
        "[observe:????????]"
        "[speak:???边?没??工???]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.anchor_tool == "search_knowledge"
    assert parsed.observe == "????????"
    assert parsed.speak == "???边?没??工???


def test_parse_legacy_action_prefix():
    raw = "[action:微?] 你好????
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("微?",)
    assert parsed.speak == "你好????


def test_parse_l2_bracket_tags_without_colon():
    raw = (
        "[action]???夹中?起头??巴?巴??
        "[speak]???????不记??！"
        "[action]不好??????????
        "[speak]来?坐?????"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.actions == (
        "???夹中?起头??巴?巴??,
        "不好??????????,
    )
    assert parsed.speak == "???????不记??！来?坐?????"
    assert parsed.session_state == "finish"
    assert "[action]" not in parsed.speak


def test_parse_l1_and_l2_mixed_in_one_turn():
    raw = "[speak:???格式][action]不?被??L2"
    parsed = parse_agent_output(raw)
    assert parsed.speak == "???格式"
    assert parsed.actions == ("不?被??L2",)


def test_parse_plain_text_as_speak():
    raw = "只??正????
    parsed = parse_agent_output(raw)
    assert parsed.speak == "只??正????
    assert parsed.session_state == "finish"


def test_parse_append_state():
    raw = "[speak:?说?句??][state:append]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "append"
    assert parsed.speak == "?说?句??


def test_parse_share_state():
    raw = "[think:???享][state:share]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "share"
    assert parsed.thought == "????


def test_stream_flush_aligns_with_tags():
    raw = (
        "[think:?]"
        "[action:???你]"
        "[speak:?????]"
        "[state:finish]"
    )
    pipeline = SpeakStreamPipeline()
    events = list(pipeline.emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    assert events[-1].final is True
    assert events[-1].meta["session_state"] == "finish"


def test_stream_append_not_final():
    raw = "[speak:第?句??][state:append]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False


def test_stream_share_not_final():
    raw = "[think:?????享][state:share]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False
    assert finish.meta["session_state"] == "share"


def test_stream_flush_l2_bracket_tags():
    raw = (
        "[think:???]"
        "[action]微?"
        "[speak]你好??
        "[state:finish]"
    )
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    action = next(event for event in events if event.kind == "action")
    assert action.text == "微?"
    speak = next(event for event in events if event.kind == "speak")
    assert speak.text == "你好??
