from __future__ import annotations

from agent.soul.speak.compose.system.output_format import SpeakOutputFormat
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
    assert "ç?°å®?æ?°å?¨" not in prompt
    assert "[observe:" not in prompt
    assert "ä¸æ?¯æ¯è½®é?½å¿?é¡»è¯´è¯? in prompt
    assert "share" in prompt
    assert "å¿?å¡«" in prompt


def test_build_anchor_request_disabled_until_tool_layer():
    req = build_anchor_request("search_knowledge")
    assert req["implemented"] is False
    assert req["tool"] == "search_knowledge"
    assert "å·¥å?·å¤?ç?å±? in req["reason"]


def test_parse_core_tags_alternating():
    raw = (
        "[think:å??ç®?ç?­æ?³ä¸?ä¸?]"
        "[action:å¾®ç¬?]"
        "[speak:ä½ å¥½å??ã??]"
        "[action:ç?¹å¤´]"
        "[speak:å¾?é«?å?´è§å?°ä½ ã??]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "å??ç®?ç?­æ?³ä¸?ä¸?
    assert parsed.actions == ("å¾®ç¬?", "ç?¹å¤´")
    assert parsed.speak == "ä½ å¥½å??ã??å¾?é«?å?´è§å?°ä½ ã??
    assert parsed.session_state == "finish"
    assert len(parsed.blocks) == 6


def test_parse_optional_anchor_and_observe():
    raw = (
        "[think:æ?¥ä¸?ä¸?]"
        "[anchor:search_knowledge]"
        "[observe:å¤?é?¨æ??æ? ç»?æ??]"
        "[speak:æ??è¿?è¾¹è¿?æ²¡è¿?ä¸?å·¥å?·ã??]"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.anchor_tool == "search_knowledge"
    assert parsed.observe == "å¤?é?¨æ??æ? ç»?æ??"
    assert parsed.speak == "æ??è¿?è¾¹è¿?æ²¡è¿?ä¸?å·¥å?·ã??


def test_parse_legacy_action_prefix():
    raw = "[action:å¾®ç¬?] ä½ å¥½å??ã??
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("å¾®ç¬?",)
    assert parsed.speak == "ä½ å¥½å??ã??


def test_parse_l2_bracket_tags_without_colon():
    raw = (
        "[action]ä»?æ ?æ?¬å¤¹ä¸­æ?¬èµ·å¤´ï¼?ç?¨å·´ç?¨å·´ç?¼ç?
        "[speak]å??ï¼?æ??ä¹?ä¼?ä¸è®°å¾?å?¢ï¼"
        "[action]ä¸å¥½æ?æ?å?°æ? æ? å?è??å??
        "[speak]æ¥ï¼?åä¸?æ?¢æ?¢è?ï¼?"
        "[state:finish]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.actions == (
        "ä»?æ ?æ?¬å¤¹ä¸­æ?¬èµ·å¤´ï¼?ç?¨å·´ç?¨å·´ç?¼ç?,
        "ä¸å¥½æ?æ?å?°æ? æ? å?è??å??,
    )
    assert parsed.speak == "å??ï¼?æ??ä¹?ä¼?ä¸è®°å¾?å?¢ï¼æ¥ï¼?åä¸?æ?¢æ?¢è?ï¼?"
    assert parsed.session_state == "finish"
    assert "[action]" not in parsed.speak


def test_parse_l1_and_l2_mixed_in_one_turn():
    raw = "[speak:æ ?å??æ ¼å¼][action]ä¸åº?è¢«å½?ä½?L2"
    parsed = parse_agent_output(raw)
    assert parsed.speak == "æ ?å??æ ¼å¼"
    assert parsed.actions == ("ä¸åº?è¢«å½?ä½?L2",)


def test_parse_plain_text_as_speak():
    raw = "åªæ??æ­£æ??ã??
    parsed = parse_agent_output(raw)
    assert parsed.speak == "åªæ??æ­£æ??ã??
    assert parsed.session_state == "finish"


def test_parse_append_state():
    raw = "[speak:å?è¯´ä¸?å¥ã??][state:append]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "append"
    assert parsed.speak == "å?è¯´ä¸?å¥ã??


def test_parse_share_state():
    raw = "[think:æ?³å??äº«][state:share]"
    parsed = parse_agent_output(raw)
    assert parsed.session_state == "share"
    assert parsed.thought == "æ?³å??äº?


def test_stream_flush_aligns_with_tags():
    raw = (
        "[think:å?¯]"
        "[action:ç??å?ä½ ]"
        "[speak:æ??å?¨ã??]"
        "[state:finish]"
    )
    pipeline = SpeakStreamPipeline()
    events = list(pipeline.emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    assert events[-1].final is True
    assert events[-1].meta["session_state"] == "finish"


def test_stream_append_not_final():
    raw = "[speak:ç¬¬ä¸?å¥ã??][state:append]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False


def test_stream_share_not_final():
    raw = "[think:å??å¤?å??äº«][state:share]"
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    finish = events[-1]
    assert finish.kind == "finish"
    assert finish.final is False
    assert finish.meta["session_state"] == "share"


def test_stream_flush_l2_bracket_tags():
    raw = (
        "[think:æ?³ä¸?ä¸?]"
        "[action]å¾®ç¬?"
        "[speak]ä½ å¥½ã??
        "[state:finish]"
    )
    events = list(SpeakStreamPipeline().emit_parsed_output("tao", raw))
    kinds = [event.kind for event in events]
    assert kinds == ["action", "speak", "state", "finish"]
    action = next(event for event in events if event.kind == "action")
    assert action.text == "å¾®ç¬?"
    speak = next(event for event in events if event.kind == "speak")
    assert speak.text == "ä½ å¥½ã??
