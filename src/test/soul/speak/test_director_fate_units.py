from __future__ import annotations

from agent.soul.speak.io.outbound.execute import execute_outbound, outbound_from_speak_text
from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest
from agent.soul.speak.io.outbound.stream.events import SpeakStreamEvent
from agent.soul.speak.responders.request_driven.directors.agent import (
    FateDiceUnit,
    RhythmCardUnit,
    build_rhythm_card,
    inject_director_frame,
    roll_fate_dice,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)
from infra.agent import Timeline
import random


def test_fate_dice_roll_range():
    rng = random.Random(7)
    first = roll_fate_dice(rng=rng)
    second = roll_fate_dice(rng=rng)
    assert 1 <= first.roll <= 100
    assert first.tendency
    assert 1 <= second.roll <= 100


def test_inject_director_frame_discards_previous_dice():
    state = SessionSchedulingState(session_id="s1")
    inject_director_frame(
        state,
        session_id="s1",
        user_text="hi",
        rhythm_card="typing_idle=True",
    )
    first_roll = int(state.director_cache["fate_dice"]["roll"])
    first_prompt = str(state.director_cache["frame_prompt"])
    inject_director_frame(
        state,
        session_id="s1",
        user_text="hi again",
        rhythm_card="typing_idle=True",
    )
    second_prompt = str(state.director_cache["frame_prompt"])
    assert "[命运骰" in second_prompt
    assert "[节奏卡片]" in second_prompt
    # 当前帧覆盖：只保留一份 frame_prompt
    assert second_prompt.count("[命运骰") == 1
    assert first_prompt != second_prompt or first_roll == int(
        state.director_cache["fate_dice"]["roll"]
    )
    # 骰不硬改 gate
    assert getattr(state, "speak_gate", "hold") in ("hold", "listen", "speak", "brew", "")


def test_rhythm_and_fate_units_on_timeline():
    timeline = Timeline()
    timeline.inject(RhythmCardUnit(card="放慢"))
    timeline.inject(FateDiceUnit(roll=42, tendency="轻微想插话"))
    text = timeline.render()
    assert "[节奏卡片]" in text
    assert "放慢" in text
    assert "[命运骰" in text
    assert "42" in text


def test_build_rhythm_card_fields():
    card = build_rhythm_card(
        typing_active=False,
        typing_idle=True,
        push_phase="idle",
        brew_queue_depth=0,
        share_wants=True,
        silence_armed=False,
        social_armed=None,
        speak_gate="hold",
    )
    assert "share_wants=True" in card
    assert "last_speak_gate=hold" in card


def test_execute_outbound_speak_finish_order():
    events: list[SpeakStreamEvent] = []

    def _emit(sid: str, event: SpeakStreamEvent) -> None:
        assert sid == "s1"
        events.append(event)

    request = OutboundRequest(
        session_id="s1",
        ops=(
            OutboundOp(kind="think", text="想"),
            OutboundOp(kind="speak", text="你好"),
            OutboundOp(kind="finish", text="", final=True),
        ),
    )
    result = execute_outbound(request, emit_fn=_emit, sleep_fn=lambda _s: None)
    assert result.answer == "你好"
    assert [e.kind for e in events] == ["thought", "agent_typing", "speak", "finish"]
    assert events[-1].text == ""

    events.clear()
    result2 = execute_outbound(
        outbound_from_speak_text("s1", "单独一句"),
        emit_fn=_emit,
        sleep_fn=lambda _s: None,
    )
    assert result2.answer == "单独一句"
    assert events[0].kind == "agent_typing"
    assert events[1].kind == "speak"
    assert events[-1].kind == "finish"
    assert events[-1].text == ""
