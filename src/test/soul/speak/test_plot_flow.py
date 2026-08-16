from __future__ import annotations

from agent.soul.speak.responders.request_driven.directors.agent.units import (
    PlotFlowUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.plot_flow import (
    PlotFlow,
)
from agent.soul.speak.responders.request_driven.screenwriter.materials import (
    WritingMaterials,
)


def test_plot_flow_advance_and_inject_unit():
    flow = PlotFlow()
    nxt = flow.advance_from_payload(
        {
            "chronicle": "双方同处帐篷，访客刚坐下。",
            "focus_now": "开场对视",
            "next_push": "用标本话题搭话",
            "beat": "访客坐下，角色留意到。",
            "beat_kind": "open",
        },
        poll_seq=1,
        turn_index=0,
    )
    assert nxt.ready
    assert nxt.version == 2
    assert len(nxt.beats) == 1
    assert nxt.beats[0].kind == "open"
    text = nxt.render_for_inject()
    assert "情景 unit" in text
    assert "开场对视" in text
    unit = PlotFlowUnit.from_flow(nxt)
    assert unit is not None
    rendered = unit.render()
    assert "开场对视" in rendered or "戏眼=" in rendered


def test_plot_flow_writes_interaction_process():
    flow = PlotFlow()
    nxt = flow.advance_from_payload(
        {
            "chronicle": "泥径未干。",
            "interaction_process": (
                "对方从屏幕外问爪印往哪；这句落在角色蹲着对泥印的当口，"
                "把注意点从蜂鸟路线拽向西坡。"
            ),
            "focus_now": "看爪印",
            "next_push": "再对一下方向",
            "beat": "角色把目光从泥印抬向西坡。",
            "beat_kind": "interact",
        },
        poll_seq=2,
        turn_index=1,
    )
    assert "爪印" in nxt.interaction_process
    assert "注意点" in nxt.interaction_process
    assert "角色说" not in nxt.interaction_process
    text = nxt.render_for_inject()
    assert "交互：" in text
    assert "爪印" in text


def test_plot_flow_keeps_fields_on_empty_payload_beat():
    flow = PlotFlow(
        chronicle="旧轨迹",
        focus_now="旧戏眼",
        next_push="旧可推",
        version=3,
    )
    nxt = flow.advance_from_payload(
        {"beat": "空档里多了一声风", "beat_kind": "push"},
        poll_seq=3,
        turn_index=1,
    )
    assert nxt.chronicle == "旧轨迹"
    assert nxt.focus_now == "旧戏眼"
    assert nxt.next_push == "旧可推"
    assert nxt.beats[-1].text == "空档里多了一声风"
    assert nxt.version == 4


def test_writing_materials_render_interaction_process():
    clay = WritingMaterials(
        last_user_text="爪印往哪边？",
        last_user_speak_at=100.0,
        last_agent_speak_at=110.0,
        recent_turns=(
            "用户：爪印往哪边？｜角色：往西，和蜂鸟路线错开了。",
        ),
    )
    process = clay.render_interaction_process(now=120.0)
    assert "爪印往哪边" in process
    assert "屏幕外" in process
    assert "注意点" in process
    assert "往西" not in process
    block = clay.render_interaction_priority(now=120.0)
    assert "如何发生" in block
    assert "往西" not in block


def test_plot_arc_aligns_pending_and_keeps_active():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    units = [
        InteractionUnit(intent="蹲着对泥印", status="active", span_polls=2),
        InteractionUnit(intent="去找蜂鸟", status="pending", span_polls=2),
        InteractionUnit(intent="整理标本", status="pending", span_polls=2),
    ]
    arc = PlotArc(summary="旧大纲", units=units, version=1, initialized_at=1.0)
    arc.realign_pending_from_payload(
        {
            "summary": "注意点被爪印拽向西坡",
            "units": [
                {"intent": "顺着爪印看向西坡", "span_polls": 2},
                {"intent": "把西坡方向记在手头", "span_polls": 2},
            ],
        }
    )
    active = arc.active_unit()
    assert active is not None
    assert active.intent == "蹲着对泥印"
    pending = [u.intent for u in arc.units if u.status == "pending"]
    assert pending == ["顺着爪印看向西坡", "把西坡方向记在手头"]
    assert arc.summary == "注意点被爪印拽向西坡"
    assert not arc.needs_screenwriter_align(exchange_count=2, aligned_at_exchange=0)
    assert arc.needs_screenwriter_align(exchange_count=3, aligned_at_exchange=0)
    while arc.total_unit_count() <= 5:
        arc.append_units_from_payload(
            {"units": [{"intent": f"补{arc.total_unit_count()}", "span_polls": 2}]}
        )
    assert arc.needs_screenwriter_align(exchange_count=0, aligned_at_exchange=0)
    assert not arc.needs_screenwriter_align(
        exchange_count=2,
        aligned_at_exchange=0,
        aligned_at_total=arc.total_unit_count(),
    )
    assert not arc.needs_screenwriter_align(
        exchange_count=3,
        aligned_at_exchange=3,
        aligned_at_total=arc.total_unit_count(),
    )


def test_narrative_wake_resets_exchange_counter():
    from types import SimpleNamespace

    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
        director_needs_init,
        mark_director_plot_aligned,
        reset_narrative_wake_counters,
        should_wake_director,
        should_wake_narrative,
    )

    arc = PlotArc(
        summary="短弧",
        units=[
            InteractionUnit(intent="蹲着对泥印", status="active", span_polls=2),
        ],
        version=1,
        initialized_at=1.0,
    )
    state = SimpleNamespace(
        plot_arc=arc,
        interaction_exchange_count=3,
        screenwriter_aligned_at_exchange=0,
        screenwriter_aligned_at_total=0,
        director_aligned_plot_fingerprint="",
    )
    assert should_wake_narrative(state) is True
    assert director_needs_init(state) is True
    assert should_wake_director(state) is True
    mark_director_plot_aligned(state)
    reset_narrative_wake_counters(state)
    assert state.interaction_exchange_count == 0
    assert state.screenwriter_aligned_at_exchange == 0
    assert state.screenwriter_aligned_at_total == arc.total_unit_count()
    assert should_wake_narrative(state) is False
    assert director_needs_init(state) is False
    assert should_wake_director(state) is False
    state.interaction_exchange_count = 3
    assert should_wake_narrative(state) is True
    assert should_wake_director(state) is False
    arc.units[0].intent = "改去顺着爪印"
    arc.version += 1
    assert should_wake_director(state) is True
