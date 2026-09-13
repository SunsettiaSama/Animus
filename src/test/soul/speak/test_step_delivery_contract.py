from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.character.context import (
    build_character_reply_request,
    build_narrative_snapshot,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    ExecutableUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.narrative_card import (
    NarrativeStageCard,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


def test_origin_user_forces_user_utterance_mode():
    state = SessionSchedulingState(session_id="s1")
    state.narrative_card = NarrativeStageCard(
        interaction_mode="no_utterance",
        user_activity="对方沉默",
    )
    snap = build_narrative_snapshot(
        state,
        origin="user",
        user_text="听得到吗",
    )
    assert "mode=user_utterance" not in snap.interaction_channel
    assert "本拍是对方刚发来的文字" in snap.interaction_channel
    assert snap.user_activity == "正在与你文字往来"
    assert snap.silence_log_text == ""


def test_user_request_binds_unique_delivery_step():
    now = time.time()
    state = SessionSchedulingState(session_id="s1")
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-due",
                open_at=now - 1,
                window_start=now - 1,
                plot_unit_id="plot-due",
                script_text="本拍台本：\n- 回应来访者",
                status="pending",
            )
        ]
    )
    req = build_character_reply_request(
        origin="user",
        session_id="s1",
        turn_index=3,
        state=state,
        user_text="哟吼",
        bind_user_step=True,
    )
    # 无 active plot_arc 时仍可绑定已有 due 节奏卡（有 plot_unit_id）
    assert req.executable_unit_id == "exec-due"
    assert "user_utterance" in req.narrative.interaction_channel or "本拍是对方刚发来的文字" in req.narrative.interaction_channel


def test_reserve_then_consume_delivery_step():
    now = time.time()
    table = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                script_text="本拍台本：\n- 看一眼水杯",
                status="pending",
            )
        ]
    )
    reserved = table.mark_reserved("exec-a")
    assert reserved is not None
    assert reserved.status == "reserved"
    assert table.due_units(now=now) == []
    consumed = table.mark_consumed(
        "exec-a",
        turn_index=1,
        trigger_id="t1",
        script_text="本拍台本：\n- 看一眼水杯",
        answer_fingerprint="这杯水凉得刚刚好。",
        plot_fingerprint="fp1",
    )
    assert consumed is not None
    assert consumed.status == "consumed"
    assert table.blocks_repeat_same_script("本拍台本：\n- 看一眼水杯")
    released = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(unit_id="exec-b", open_at=now - 1, status="reserved")
        ]
    )
    assert released.release_reserved("exec-b").status == "pending"
