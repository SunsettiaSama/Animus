from __future__ import annotations

from agent.soul.speak.io.outbound.stream.parse.incremental import IncrementalTagStreamParser
from agent.soul.speak.io.outbound.stream.sanitize import sanitize_push_text


def test_sanitize_push_text_strips_close_tags():
    assert sanitize_push_text("你好[/speak]") == "你好"
    assert sanitize_push_text("[/speak]") == ""
    assert sanitize_push_text("歪头[/action]") == "歪头"


def test_plain_speak_after_tag_uses_single_bubble_stream():
    """标签后的裸文本须 delta 追加，勿每 token 一个 phase:end 气泡。"""
    events = []
    parser = IncrementalTagStreamParser(emit_fn=lambda _sid, ev: events.append(ev))
    raw = "[speak]你好。[/speak][action]歪头[/action]露米那家伙"
    for ch in raw:
        list(parser.push("tao", ch))
    list(parser.flush("tao"))
    speak_ends = [
        e for e in events
        if e.kind == "speak" and (e.meta or {}).get("phase") == "end" and e.text.strip()
    ]
    assert not speak_ends
    speak_deltas = "".join(
        e.text for e in events
        if e.kind == "speak" and (e.meta or {}).get("phase") == "delta"
    )
    assert "\u9732" in speak_deltas
    assert "\u7c73" in speak_deltas


def test_incremental_state_hybrid_l1_l2_close():
    """[state:finish[/state] 不得把 [/state] 残片写入 session_state。"""
    events = []
    parser = IncrementalTagStreamParser(emit_fn=lambda _sid, ev: events.append(ev))
    raw = "[state:finish[/state]"
    for ch in raw:
        list(parser.push("tao", ch))
    list(parser.flush("tao"))
    state_events = [e for e in events if e.kind == "state"]
    assert len(state_events) == 1
    assert state_events[0].text == "finish"
    assert state_events[0].meta["session_state"] == "finish"


def test_incremental_stream_excludes_close_tags():
    events = []
    parser = IncrementalTagStreamParser(emit_fn=lambda _sid, ev: events.append(ev))
    raw = "[action]歪了歪头[/action][speak]诶？[/speak][state]finish[/state]"
    for ch in raw:
        list(parser.push("tao", ch))
    list(parser.flush("tao"))
    texts = [e.text for e in events if e.kind in ("speak", "action") and e.text]
    assert all("[/" not in t for t in texts)
    assert "歪了歪头" in "".join(texts)
    assert "诶？" in "".join(texts)


def test_parse_agent_output_xml_pairs():
    from agent.soul.speak.io.outbound.stream import parse_agent_output

    raw = (
        "[think]内部[/think]"
        "[speak]你好。[/speak]"
        "[action]歪头[/action]"
        "[state]finish[/state]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "内部"
    assert parsed.speak == "你好。"
    assert parsed.actions == ("歪头",)
    assert parsed.session_state == "finish"


def test_parse_html_close_tags_and_action_marker():
    from agent.soul.speak.io.outbound.stream import parse_agent_output

    raw = (
        "（动作）莉奈娅微微一怔，露出不好意思的笑</action>\n"
        "哎呀，抱歉抱歉，所以你是哪位来着？</speak>"
    )
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("莉奈娅微微一怔，露出不好意思的笑",)
    assert "抱歉抱歉" in parsed.speak
    assert "</speak>" not in parsed.speak
    assert "</action>" not in (parsed.actions[0] if parsed.actions else "")


def test_parse_mixed_bracket_open_html_close():
    from agent.soul.speak.io.outbound.stream import parse_agent_output

    raw = (
        "[think]想一下[/think]"
        "[action]歪头[/action]"
        "[speak]你好。[/speak]"
    )
    parsed = parse_agent_output(raw)
    assert parsed.thought == "想一下"
    assert parsed.actions == ("歪头",)
    assert parsed.speak == "你好。"


def test_parse_plain_action_markers_only():
    from agent.soul.speak.io.outbound.stream import parse_agent_output

    raw = "（动作）端详了几秒\n当然记得啦！"
    parsed = parse_agent_output(raw)
    assert parsed.actions == ("端详了几秒",)
    assert parsed.speak == "当然记得啦！"
    """L2 [tag]…[/tag] 流式 delta 须为增量；前端按 delta 追加，重复推送全文会叠字。"""
    events = []
    parser = IncrementalTagStreamParser(emit_fn=lambda _sid, ev: events.append(ev))
    raw = "[action]眼睛转了转，突然凑近[/action][speak]好吧好吧，看在你这么机灵的份上[/speak]"
    for ch in raw:
        list(parser.push("tao", ch))
    list(parser.flush("tao"))

    def _display(kind: str) -> str:
        return "".join(
            e.text
            for e in events
            if e.kind == kind and (e.meta or {}).get("phase") == "delta"
        )

    action_text = _display("action")
    speak_text = _display("speak")
    assert action_text == "眼睛转了转，突然凑近"
    assert speak_text == "好吧好吧，看在你这么机灵的份上"
    assert action_text.count("眼睛转了转") == 1
    assert speak_text.count("好吧好吧") == 1
