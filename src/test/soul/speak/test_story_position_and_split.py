"""剧情位置坐标 + speak 拆分 + 预约近端取消的契约测试。"""

from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.character.interaction import (
    export_interaction_record,
    note_character_exchange,
)
from agent.soul.speak.responders.request_driven.interpreter import interpret_role_output
from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
    InteractionUnit,
    PlotArc,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    CharacterSpeakAgenda,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


def _make_arc() -> PlotArc:
    arc = PlotArc(
        summary="修好那只旧钟，并弄清它的来历。",
        units=[
            InteractionUnit(intent="拆开钟壳检查机芯", status="active", span_polls=2, estimate_sec=40),
            InteractionUnit(intent="对照图鉴辨认机芯产地", status="pending", span_polls=2, estimate_sec=75),
            InteractionUnit(intent="把齿轮归位上油", status="pending", span_polls=2, estimate_sec=40),
        ],
    )
    arc.current_index = 0
    return arc


def test_render_for_inject_shows_position_and_next_steps():
    arc = _make_arc()
    text = arc.render_for_inject(max_pending=4)
    assert "[故事线｜第 1/3 步]" in text
    assert "当前步骤（第 1 步）：拆开钟壳检查机芯（约 40 秒）" in text
    assert "- 第 2 步：对照图鉴辨认机芯产地（约 75 秒）" in text
    assert "- 第 3 步：把齿轮归位上油（约 40 秒）" in text


def test_render_for_inject_position_advances_after_history():
    arc = _make_arc()
    first = arc.units[0]
    arc.units = arc.units[1:]
    arc.unit_history.append({"intent": first.intent, "unit_id": first.unit_id})
    # active_unit() 按 current_index 取；pending 列表按 status 过滤——两者都要到位
    arc.current_index = 0
    arc.units[0].status = "active"
    text = arc.render_for_inject()
    assert "[故事线｜第 2/3 步]" in text
    assert "当前步骤（第 2 步）：对照图鉴辨认机芯产地" in text
    assert "- 第 3 步：把齿轮归位上油" in text


def test_interaction_record_reports_exchange_rounds():
    state = SessionSchedulingState(session_id="rounds")
    state.interaction_exchange_count = 5
    note_character_exchange(state, user_text="在吗", agent_text="在。")
    rec = export_interaction_record(state)
    assert rec.exchange_rounds == 5
    assert "你们已经往来了 5 轮。" in rec.render_for_character()


def test_ledger_splits_multi_speak_into_separate_entries():
    state = SessionSchedulingState(session_id="split")
    note_character_exchange(
        state,
        user_text="写到哪了",
        agent_text="没呢，写了一半，卡在措辞上。\n\n笔搁那儿半天了，倒是旁边那堆石头分得挺快。",
    )
    rec = export_interaction_record(state)
    assert "你：没呢，写了一半，卡在措辞上。" in rec.recent_turns
    assert "你：笔搁那儿半天了，倒是旁边那堆石头分得挺快。" in rec.recent_turns
    # 两条独立消息，不再是 join 后的一坨
    assert not any("措辞上。\\n" in t for t in rec.recent_turns)


def test_interpreter_splits_blank_line_speak_into_multiple_emits():
    timeline = interpret_role_output(
        "<think>想一句</think>"
        "<speak>没呢，写了一半，卡在措辞上。</speak>"
        "<speak>笔搁那儿半天了。</speak>"
        "<speak>第一句。\n\n第二句。</speak>"
    )
    emits = [op for op in timeline.ops if op.kind == "emit"]
    assert [op.texts[0] for op in emits] == [
        "没呢，写了一半，卡在措辞上。",
        "笔搁那儿半天了。",
        "第一句。",
        "第二句。",
    ]


def test_agenda_cancel_near_future_after_exchange():
    now = time.time()
    agenda = CharacterSpeakAgenda()
    agenda.note_event(now)
    near = agenda.add_speak(at=now + 30, source="director", reason="近端", plot_unit_id="p1", rng=None)
    far = agenda.add_speak(at=now + 600, source="director", reason="远端", plot_unit_id="p2", rng=None)
    cancelled = agenda.cancel_near_future(now=now, window_sec=90)
    assert cancelled == 1
    assert near.status == "cancelled"
    assert far.status == "pending"
