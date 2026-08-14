from __future__ import annotations

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven import SpeakRole, interpret_role_output, parse_role_blocks
from agent.soul.speak.responders.request_driven.delivery_bridge import timeline_to_delivery_plan


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
    assert [op.kind for op in timeline.ops] == ["think", "wait", "emit", "body"]
    assert timeline.ops[0].body == "先打个招呼"


def test_execute_timeline_emits_four_bubble_kinds():
    from agent.soul.speak.responders.request_driven.delivery_bridge import execute_timeline_sync

    timeline = interpret_role_output(
        "[think]观察一下[/think]"
        "<speak action>wait 0</speak action>"
        "<speak context>你好</speak context>"
        "<speak action>emit</speak action>"
        "<body action>点头</body action>"
    )
    result = execute_timeline_sync(timeline, sleep_fn=lambda _s: None)
    kinds = [e.kind for e in result.events]
    assert kinds == ["thought", "state", "speak", "action"]
    assert [e.meta.get("field") for e in result.events] == [
        "thought",
        "wait",
        "speak",
        "body",
    ]
    assert result.thoughts == ("观察一下",)
    assert result.answer == "你好"
    assert result.body_actions == ("点头",)


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
    assert kinds == ["wait", "emit", "body", "silence"]
    emit = timeline.ops[1]
    assert emit.texts == ("你好", "补充")
    assert timeline.ops[0].wait_ms == 1500
    assert timeline.ops[3].meta.get("silence") is True


def test_timeline_to_delivery_plan_uses_role_pacing():
    timeline = interpret_role_output(
        "<speak action>wait 2</speak action>"
        "<speak context>台词</speak context>"
        "<speak action>emit</speak action>"
    )
    plan = timeline_to_delivery_plan(timeline, turn_index=3, plan_id="p1")
    assert not plan.is_empty
    assert plan.segments[0].text == "台词"
    assert plan.segments[0].wait_ms == 2000
    assert plan.segments[0].wait_reason == "role_wait"


def test_speak_role_run_turn_with_override():
    from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.dynamic_layer import (
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
    assert "动态层·记忆" in _prompt.system_extra
    # 无导演调度时不得自动灌记忆
    bare = role.prepare(view, user_text="在吗")
    assert "动态层·记忆" not in bare.system_extra
    assert "本轮导演未调度" in bare.system_extra
