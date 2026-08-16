from __future__ import annotations

import time
from types import SimpleNamespace

from agent.soul.speak.responders.request_driven.character.consume import (
    note_plot_bound_delivery,
)
from agent.soul.speak.responders.request_driven.character.context import (
    bind_delivery_step_for_user,
)
from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
    seed_plot_unit_consumption_queue,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    ExecutableUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
    InteractionUnit,
    PlotArc,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.narrative_card import (
    NarrativeStageCard,
    SilenceLog,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.plot_flow import PlotFlow
from agent.soul.speak.responders.request_driven.orchestrator.state.core.presence_card import (
    CharacterPresenceCard,
)
from agent.soul.speak.responders.request_driven.screenwriter.writer import Screenwriter


def _arc_four_steps() -> PlotArc:
    arc = PlotArc(
        summary="晨光下旋开标本台锁扣，并保护蜡膜对齐",
        evidence="书签、横纹、蜡膜、第十八格针尖",
        units=[
            InteractionUnit(intent="书签边缘抵住锁扣槽口", span_polls=2),
            InteractionUnit(intent="沿横纹末端方向缓旋半圈", span_polls=2),
            InteractionUnit(intent="确认阻力松动且蜡膜未裂", span_polls=2),
            InteractionUnit(intent="把针尖凸起重新核对对齐", span_polls=2),
        ],
    )
    arc._activate_head(poll_seq=0)
    return arc


def test_character_delivery_notes_without_advancing_plot():
    """角色交付只记账，不推进 plot_arc；完成权在导演→编剧。"""
    arc = _arc_four_steps()
    first_id = arc.units[0].unit_id
    state = SimpleNamespace(
        plot_arc=arc,
        poll_seq=1,
        director_cache={},
        notes=[],
        character_rhythm_schedule=CharacterRhythmSchedule(),
    )
    noted = note_plot_bound_delivery(
        state,
        plot_unit_ids=(first_id,),
        reason="test_delivery",
    )
    assert noted == "书签边缘抵住锁扣槽口"
    assert arc.units[0].status == "active"
    assert not arc.unit_history
    evidence = state.director_cache.get("plot_unit_delivery_evidence") or []
    assert len(evidence) == 1
    assert evidence[0]["plot_unit_id"] == first_id


def test_character_delivery_ignores_non_active_bind():
    arc = _arc_four_steps()
    state = SimpleNamespace(
        plot_arc=arc,
        poll_seq=1,
        director_cache={},
        notes=[],
        character_rhythm_schedule=CharacterRhythmSchedule(),
    )
    noted = note_plot_bound_delivery(
        state,
        plot_unit_ids=(arc.units[2].unit_id,),
        reason="test",
    )
    assert noted == ""
    assert arc.units[0].status == "active"
    assert not (state.director_cache.get("plot_unit_delivery_evidence") or [])


def test_director_confirm_is_sole_plot_advance():
    arc = _arc_four_steps()
    first_id = arc.units[0].unit_id
    state = SimpleNamespace(
        session_id="s-sole",
        plot_arc=arc,
        plot_flow=PlotFlow(),
        poll_seq=2,
        director_cache={},
        notes=[],
        character_rhythm_schedule=CharacterRhythmSchedule(),
        fate_speak_desire=50,
        presence_card=CharacterPresenceCard(),
        narrative_card=NarrativeStageCard(),
        silence_log=SilenceLog(),
        screenwriter_continued_at_poll=0,
        last_real_user_text="",
    )
    note_plot_bound_delivery(state, plot_unit_ids=(first_id,), reason="delivery")
    sw = Screenwriter(llm=None)
    nxt = sw.confirm_interaction_unit_complete(
        state,
        poll_seq=2,
        reason="director_ok",
        session_id="s-sole",
        unit_id=first_id,
    )
    assert any(h.get("unit_id") == first_id for h in arc.unit_history)
    assert all(u.unit_id != first_id for u in arc.units)
    assert nxt is not None
    assert state.director_cache.get("last_completed_plot_unit_id") == first_id
    # 重复确认同一张卡应忽略
    assert (
        sw.confirm_interaction_unit_complete(
            state,
            poll_seq=2,
            reason="dup",
            session_id="s-sole",
            unit_id=first_id,
        )
        is None
    )


def test_user_bind_keeps_remaining_plot_queue():
    arc = _arc_four_steps()
    now = time.time()
    rhythm = seed_plot_unit_consumption_queue(
        CharacterRhythmSchedule(),
        now=now,
        plot_arc=arc,
    )
    rhythm.executable_units.append(
        ExecutableUnit(
            open_at=now + 5,
            reason="ladder_placeholder",
            status="pending",
            plot_unit_ids=(),
        )
    )
    state = SimpleNamespace(
        plot_arc=arc,
        character_rhythm_schedule=rhythm,
        director_cache={},
        pending_character_handoff={"x": 1},
    )
    step_id, plot_ids, _ = bind_delivery_step_for_user(
        state,
        session_id="sess-queue-01",
        turn_index=1,
    )
    assert step_id
    assert plot_ids == (arc.units[0].unit_id,)
    pending = [e for e in rhythm.executable_units if e.status == "pending"]
    assert len(pending) == 4
    assert all(e.plot_unit_ids for e in pending)
    cancelled = [e for e in rhythm.executable_units if e.status == "cancelled"]
    assert any(e.reason == "ladder_placeholder" for e in cancelled)
    assert state.pending_character_handoff is None
