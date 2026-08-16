from __future__ import annotations

from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven import SpeakRole, interpret_role_output, parse_role_blocks
from agent.soul.speak.responders.request_driven.delivery_bridge import timeline_to_delivery_plan
from agent.soul.speak.responders.request_driven.layers import _ROLE_PROTOCOL_HINT, build_dialogue_frame
from agent.soul.speak.responders.request_driven.protocol.scrub import scrub_compose_markup


def test_role_protocol_hint_speak_only():
    assert "[speak]" not in _ROLE_PROTOCOL_HINT
    assert "[action]" not in _ROLE_PROTOCOL_HINT
    assert "[state]" not in _ROLE_PROTOCOL_HINT
    assert "<speak>一条短消息</speak>" in _ROLE_PROTOCOL_HINT
    assert "<body action>" not in _ROLE_PROTOCOL_HINT
    assert "短消息" in _ROLE_PROTOCOL_HINT
    assert 'i="' not in _ROLE_PROTOCOL_HINT


def test_parse_keeps_plain_text_between_body_tags_as_speak():
    raw = (
        "<body action>手指轻轻翻开夹着借阅卡的那一页</body action>\n"
        "嗯，旧时代的物件往往比人更会讲故事。\n"
        "</body action>有意思的是，这卡上的名字……</body action>\n"
        "写的是我的名字。\n"
        "</body action>"
    )
    blocks = parse_role_blocks(raw)
    assert [b.kind for b in blocks] == ["body_action", "speak"]
    assert "手指轻轻翻开" in blocks[0].content
    assert "<body" not in blocks[1].content
    assert "</body" not in blocks[1].content
    assert "旧时代的物件" in blocks[1].content
    assert "写的是我的名字" in blocks[1].content
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == ["emit"]
    assert "<body" not in timeline.answer_text


def test_parse_dedups_consecutive_identical_body():
    raw = (
        "<body action>放下竹篾，双手交叠搁在膝上</body action>"
        "<body action>放下竹篾，双手交叠搁在膝上</body action>"
    )
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == []


def test_parse_assigns_order_by_appearance():
    raw = (
        "<body action>指尖停在凹槽边缘</body action>"
        "<speak>这儿有道缝</speak>"
        "<body action>俯身再看一眼</body action>"
        "<speak>你也凑近点</speak>"
    )
    blocks = parse_role_blocks(raw)
    assert [b.kind for b in blocks] == ["body_action", "speak", "body_action", "speak"]
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == ["emit", "emit"]
    assert [op.meta.get("order") for op in timeline.ops] == [0, 1]


def test_orphan_close_tags_are_speak_not_second_body():
    raw = (
        "<body action>放下竹篾，双手交叠搁在膝上</body action>"
        "</body action>放下竹篾，双手交叠搁在膝上</body action>"
    )
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == []
    assert timeline.answer_text == ""


def test_scrub_compose_markup_keeps_prose_only():
    raw = (
        "[think]内心[/think]"
        "[speak]你好呀[/speak]"
        "[action]点头[/action]"
        "[state]finish[/state]"
    )
    assert scrub_compose_markup(raw) == "你好呀\n点头"


def test_dialogue_frame_scrubs_compose_history():
    view = RoleContextView(
        session_id="s",
        working_turns=(
            ("在吗", "[speak]在的[/speak][action]挥手[/action][state]finish[/state]"),
        ),
    )
    frame = build_dialogue_frame(view)
    assert "[speak]" not in frame
    assert "[state]" not in frame
    assert "在的" in frame
    assert "挥手" in frame


def test_compose_bracket_tags_are_not_role_blocks():
    """角色解析器不再认 compose 方括号；仅 think 会被吃掉。"""
    raw = (
        "[think]想打招呼[/think]"
        "[speak]你好呀[/speak]"
        "[action]点头[/action]"
        "[state]finish[/state]"
    )
    blocks = parse_role_blocks(raw)
    assert [b.kind for b in blocks] == ["think"]
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == ["think"]
    assert timeline.answer_text == ""


def test_parse_interleaved_html_blocks():
    raw = """
<speak action>wait 2</speak action>
<speak context>第一句</speak context>
<speak context>第二句</speak context>
<speak action>emit</speak action>
<body action>低头整理袖口</body action>
<speak action>silence 1</speak action>
"""
    blocks = parse_role_blocks(raw)
    kinds = [b.kind for b in blocks]
    assert kinds == [
        "speak_action",
        "speak_context",
        "speak_context",
        "speak_action",
        "body_action",
        "speak_action",
    ]


def test_parse_think_with_role_html_keeps_order():
    raw = (
        "[think]先打个招呼[/think]"
        "<speak action>wait 1</speak action>"
        "<speak context>嘿，这儿呢</speak context>"
        "<speak action>emit</speak action>"
        "<body action>从放大镜前抬起头</body action>"
    )
    blocks = parse_role_blocks(raw)
    assert [b.kind for b in blocks] == [
        "think",
        "speak_action",
        "speak_context",
        "speak_action",
        "body_action",
    ]
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == ["think", "wait", "emit"]
    assert timeline.ops[0].body == "先打个招呼"


def test_execute_timeline_emits_speak_with_order():
    from agent.soul.speak.responders.request_driven.delivery_bridge import execute_timeline_sync

    timeline = interpret_role_output("<speak>你好</speak>")
    result = execute_timeline_sync(timeline, sleep_fn=lambda _s: None)
    kinds = [e.kind for e in result.events]
    assert kinds == ["agent_typing", "speak"]
    assert [e.meta.get("field") for e in result.events] == ["typing", "speak"]
    assert result.events[1].meta.get("order") == 0
    assert result.thoughts == ()
    assert result.answer == "你好"
    assert result.body_actions == ()


def test_execute_timeline_interleaves_body_and_speak_with_order():
    from agent.soul.speak.responders.request_driven.delivery_bridge import (
        execute_timeline_sync,
        timeline_to_outbound_request,
    )

    raw = (
        "<body action>指尖停在凹槽边缘</body action>"
        "<speak>这儿有道缝</speak>"
        "<body action>俯身再看一眼</body action>"
        "<speak>你也凑近点</speak>"
    )
    timeline = interpret_role_output(raw)
    assert [op.kind for op in timeline.ops] == ["emit", "emit"]
    request = timeline_to_outbound_request(timeline, session_id="s1", finish=True)
    kinds = [op.kind for op in request.ops]
    assert kinds == ["speak", "speak", "finish"]
    result = execute_timeline_sync(timeline, sleep_fn=lambda _s: None)
    visible = [e for e in result.events if e.kind in ("action", "speak")]
    assert [e.kind for e in visible] == ["speak", "speak"]
    assert result.body_actions == ()
    assert "这儿有道缝" in result.answer and "你也凑近点" in result.answer


def test_interpret_timeline_emit_segments_and_wait():
    raw = """
[speak_action:wait 1.5]
[speak_context:你好]
[speak_context:补充]
[speak_action:emit]
[body_action:点头]
[speak_action:silence 2]
"""
    timeline = interpret_role_output(raw)
    kinds = [op.kind for op in timeline.ops]
    assert kinds == ["wait", "emit", "silence"]
    emit = timeline.ops[1]
    assert emit.texts == ("你好", "补充")
    assert timeline.ops[0].wait_ms == 1500
    assert timeline.ops[2].meta.get("silence") is True


def test_timeline_to_delivery_plan_uses_one_complete_speak():
    timeline = interpret_role_output("<speak>台词</speak>")
    plan = timeline_to_delivery_plan(timeline, turn_index=3, plan_id="p1")
    assert not plan.is_empty
    assert plan.segments[0].text == "台词"
    assert plan.segments[0].wait_ms == 0
    assert plan.segments[0].wait_reason == "character_speak"


def test_speak_role_run_turn_with_override():
    from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
        DynamicLayerMaterials,
        DynamicLayerSchedule,
    )

    role = SpeakRole(generate_fn=lambda system, user: "unused")
    view = RoleContextView(session_id="s", memory_texts=("热茶",))
    materials = DynamicLayerMaterials(
        session_id="s",
        memory_ids=("m1",),
        memory_texts=("热茶",),
    )
    schedule = DynamicLayerSchedule(
        inject_memory=True,
        memory_unit_ids=("m1",),
        reason="test",
    )
    raw = (
        "<speak context>喝杯茶吧</speak context>"
        "<speak action>emit</speak action>"
    )
    _prompt, _raw, timeline, result = role.run_turn(
        view,
        user_text="在吗",
        raw_override=raw,
        turn_index=1,
        materials=materials,
        schedule=schedule,
    )
    assert result.answer == "喝杯茶吧"
    assert timeline.spoken_texts == ("喝杯茶吧",)
    assert "记忆卡片" in _prompt.system_extra or "一次性记忆" in _prompt.system_extra
    # 无导演调度时不得自动灌记忆
    bare = role.prepare(view, user_text="在吗")
    assert "记忆卡片" not in bare.system_extra
    assert "一次性记忆" not in bare.system_extra
    assert "即时往来" in bare.system_extra or "对方刚发来" in bare.system_extra
    assert "「你」指用户" in bare.system_extra
    assert "「我」指你自己" in bare.system_extra
    assert "只指 NPC" in bare.system_extra
    assert "【回复格式】" in bare.system_extra
    assert "<body action>" not in bare.system_extra
    assert "<speak>" in bare.system_extra
