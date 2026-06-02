from __future__ import annotations

from agent.soul.speak.orchestrator.system.output_format import SpeakOutputFormat
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
    assert "?°å??°å?? not in prompt
    assert "[observe:" not in prompt
    assert "ä¸æ?¯æ¯è½®é?½å?é¡»è¯´è¯? in prompt
    assert "share" in prompt
    assert "å¿?å¡? in prompt


def test_build_anchor_request_disabled_until_tool_layer():
    req = build_anchor_request("search_knowledge")
    assert req["implemented"] is False
    assert req["tool"] == "search_knowledge"
    assert "å·¥å?·å?ç?å±? in req["reason"]


def test_parse_core_tags_alternating():
    raw = (
        "[think:??ç®??­æ?³ä?ä¸?]"
        "[action:å¾®ç?]"
        "[speak:ä½ å¥½????]"
        "[action:?¹å¤´]"
        "[speak:å¾?é«??´è§?°ä½ ??]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "??ç®??­æ?³ä?ä¸?
    assert parsed.actions == ("å¾®ç?", "?¹å¤´")
    assert parsed.speak == "ä½ å¥½????å¾?é«??´è§?°ä½ ??
    assert parsed.session_state == "finish"
    assert len(parsed.blocks) == 6


def test_parse_optional_anchor_and_observe():
    raw = (
        "[think:?¥ä?ä¸?]"
        "[anchor:search_knowledge]"
        "[observe:å¤??¨æ??? ç???]"
        "[speak:??è¿?è¾¹è?æ²¡è?ä¸?å·¥å?·ã??]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.anchor_tool == "search_knowledge"
    assert parsed.observe == "å¤??¨æ??? ç???"
    assert parsed.speak == "??è¿?è¾¹è?æ²¡è?ä¸?å·¥å?·ã??


def test_parse_legacy_action_prefix():
    raw = "[action:å¾®ç?] ä½ å¥½????
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("å¾®ç?",)
    assert parsed.speak == "ä½ å¥½????


def test_parse_l2_bracket_tags_without_colon():
    raw = (
        "[action]ä»?æ ??¬å¤¹ä¸­æ?¬èµ·å¤´ï??¨å·´?¨å·´?¼ç?
        "[speak]??ï¼???ä¹?ä¼?ä¸è®°å¾??¢ï¼"
        "[action]ä¸å¥½?æ?å?°æ? æ? å?????
        "[speak]æ¥ï?åä??¢æ?¢è?ï¼?"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.actions == (
        "ä»?æ ??¬å¤¹ä¸­æ?¬èµ·å¤´ï??¨å·´?¨å·´?¼ç?,
        "ä¸å¥½?æ?å?°æ? æ? å?????,
    )
    assert parsed.speak == "??ï¼???ä¹?ä¼?ä¸è®°å¾??¢ï¼æ¥ï?åä??¢æ?¢è?ï¼?"
    assert parsed.session_state == "finish"
    assert "[action]" not in parsed.speak


def test_parse_l1_and_l2_mixed_in_one_turn():
    raw = "[speak:æ ???æ ¼å¼][action]ä¸å?è¢«å?ä½?L2"
    parsed = parse_agent_output(raw)
    assert parsed.speak == "æ ???æ ¼å¼"
    assert parsed.actions == ("ä¸å?è¢«å?ä½?L2",)


def test_parse_plain_text_as_speak():
    raw = "åªæ??æ­£æ????
    parsed = parse_agent_output(raw)
    assert parsed.speak == "åªæ??æ­£æ????
    assert parsed.session_state == "finish"


def test_parse_append_state():
    raw = "[speak:?è¯´ä¸?å¥ã??][state:append]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "append"
    assert parsed.speak == "?è¯´ä¸?å¥ã??


def test_parse_share_state():
    raw = "[think:?³å??äº«][state:share]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "share"
    assert parsed.thought == "?³å??äº?


def test_stream_flush_aligns_with_tags():
    raw = (
        "[think:?¯]"
        "[action:??å?ä½ ]"
        "[speak:???¨ã??]"
        "[state:finish]"
    )
    pipeline = SpeakStreamPipeline()
    events = list(pipeline.emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    assert events[-1].final is True
    assert events[-1].meta["session_state"] == "finish"


def test_stream_append_not_final():
    raw = "[speak:ç¬¬ä?å¥ã??][state:append]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False


def test_stream_share_not_final():
    raw = "[think:??å¤???äº«][state:share]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False
    assert finish.meta["session_state"] == "share"


def test_stream_flush_l2_bracket_tags():
    raw = (
        "[think:?³ä?ä¸?]"
        "[action]å¾®ç?"
        "[speak]ä½ å¥½??
        "[state:finish]"
    )
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    action = next(event for event in events if event.kind == "action")
    assert action.text == "å¾®ç?"
    speak = next(event for event in events if event.kind == "speak")
    assert speak.text == "ä½ å¥½??
