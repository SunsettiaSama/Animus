from __future__ import annotations

import random
import time

from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
    RhythmScheduleDirector,
    apply_rhythm_schedule_output,
    seed_plot_unit_consumption_queue,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    ExecutableUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    BOOKING_GAP_MIN_SEC,
    CharacterSpeakAgenda,
    sample_booking_gap_sec,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


def test_executable_unit_enrich_one_to_one_and_legacy_kwargs():
    unit = ExecutableUnit(
        plot_unit_ids=("plot-1",),
        focus="你蹲在泥地旁看爪印",
        intent="你心里发紧，先不开口",
        direction="你先把爪印看清楚",
        exit="你自然停住，不硬问",
    )
    assert unit.plot_unit_id == "plot-1"
    assert unit.plot_unit_ids == ("plot-1",)
    assert unit.detail.startswith("你蹲")
    assert unit.inner.startswith("你心里")
    assert unit.has_enrichment()
    assert "你手头" in unit.render_enrichment()


def test_needs_refill_and_covered_plot_ids():
    table = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(plot_unit_id="a", status="pending", detail="你做一步"),
            ExecutableUnit(plot_unit_id="b", status="pending", detail="你再做一步"),
        ]
    )
    assert table.live_unit_count() == 2
    assert table.needs_refill(min_live=5)
    assert table.covered_plot_ids() == {"a", "b"}
    filled = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(plot_unit_id=f"p{i}", status="pending", detail="x")
            for i in range(5)
        ]
    )
    assert not filled.needs_refill(min_live=5)


def test_due_units_and_mark_consumed_records_history():
    now = time.time()
    table = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                open_at=now - 1,
                window_start=now - 1,
                reason="now",
                status="pending",
                plot_unit_id="p1",
            ),
            ExecutableUnit(
                open_at=now + 30,
                window_start=now + 30,
                reason="later",
                status="pending",
                plot_unit_id="p2",
            ),
        ]
    )
    due = table.due_units(now=now)
    assert len(due) == 1
    assert due[0].reason == "now"
    consumed = table.mark_consumed(
        due[0].unit_id,
        turn_index=7,
        trigger_id="trigger-7",
        consumed_at=123.0,
    )
    assert consumed is not None
    assert consumed.status == "consumed"
    assert table.due_units(now=now) == []
    assert table.consumption_history[0]["plot_unit_id"] == "p1"
    restored = CharacterRhythmSchedule.from_dict(table.snapshot())
    assert "最近已消费" in restored.render_for_director()


def test_replace_keeps_fired_units_and_one_to_one():
    now = time.time()
    current = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-keep",
                open_at=now - 5,
                status="fired",
                reason="done",
                plot_unit_id="old",
            )
        ],
        version=3,
    )
    nxt = current.replace_from_director_payload(
        {
            "executable_units": [
                {
                    "unit_id": "exec-keep",
                    "open_at": now,
                    "status": "pending",
                    "reason": "rewrite",
                    "plot_unit_id": "old",
                },
                {
                    "plot_unit_id": "new-a",
                    "detail": "你看门口",
                    "reason": "new",
                    "status": "pending",
                },
                {
                    "plot_unit_id": "new-a",
                    "detail": "重复同 plot 应丢掉",
                    "reason": "dup",
                    "status": "pending",
                },
            ],
            "private": {
                "thinking": "还在打量对方",
                "noticing": "门口站着人",
                "wanting": "先搭一句",
            },
        },
        poll_seq=2,
        now=now,
    )
    by_id = {e.unit_id: e for e in nxt.executable_units}
    assert by_id["exec-keep"].status == "fired"
    assert sum(1 for e in nxt.executable_units if e.plot_unit_id == "new-a") == 1
    assert nxt.private.thinking == "还在打量对方"
    assert nxt.version == 4


def test_apply_rhythm_schedule_writes_director_timeline():
    state = SessionSchedulingState(session_id="s1")
    now = time.time()
    schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                open_at=now,
                window_start=now,
                status="pending",
                plot_unit_id="p1",
                detail="你蹲下",
            )
        ],
        revised_at=now,
        poll_seq=1,
    )
    from agent.soul.speak.responders.request_driven.directors.base import (
        DirectorOutput,
    )

    apply_rhythm_schedule_output(
        state,
        DirectorOutput(
            director="rhythm_schedule",
            payload={
                "schedule": schedule.snapshot(),
                "timeline": [
                    {"at": now + 5, "plot_unit_id": "p1", "reason": "开窗"},
                ],
            },
        ),
    )
    assert state.character_rhythm_schedule.executable_units
    assert "pending_unit_complete" not in state.director_cache
    assert state.speak_agenda.entries
    assert state.speak_agenda.entries[0].source == "director"
    assert state.speak_agenda.entries[0].at >= now + BOOKING_GAP_MIN_SEC - 0.01


def test_agenda_waits_for_previous_action_duration():
    now = time.time()
    agenda = CharacterSpeakAgenda()
    first = agenda.add_speak(
        at=now + 5,
        source="director",
        plot_unit_id="read",
        reason="读信",
        duration_sec=80,
        enforce=False,
    )
    second = agenda.add_speak(
        at=now + 8,
        source="director",
        plot_unit_id="fold",
        reason="折信",
        duration_sec=20,
        rng=random.Random(3),
    )
    assert first.duration_sec == 80
    assert second.at >= first.at + 80 - 0.01


def test_director_parses_duration_and_chains_timeline():
    from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
        estimate_action_duration_sec,
    )

    assert estimate_action_duration_sec("拂去书脊灰尘，将书从架上取下") == 18.0
    assert estimate_action_duration_sec("翻开信纸读完内容") == 75.0
    director = RhythmScheduleDirector(_FakeLLM())  # type: ignore[arg-type]
    now = time.time()
    schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                plot_unit_id="p-take",
                window_start=now,
                window_end=now + 18,
                status="pending",
            ),
            ExecutableUnit(
                plot_unit_id="p-read",
                window_start=now + 18,
                window_end=now + 93,
                status="pending",
            ),
        ]
    )
    timeline = director._parse_timeline(
        {
            "timeline": [
                {"at_sec": 5, "plot_unit_id": "p-take", "reason": "抽书"},
                {"at_sec": 8, "plot_unit_id": "p-read", "reason": "读信"},
            ]
        },
        now=now,
        schedule=schedule,
    )
    assert timeline[0]["duration_sec"] == 18
    assert timeline[1]["at"] >= timeline[0]["at"] + 18 - 0.01
    unit = director._parse_unit_item(
        {
            "plot_unit_id": "p-new",
            "detail": "你抽出那本绿布面书",
            "duration_sec": 18,
            "window_start_sec": 0,
            "reason": "抽书大约十八秒",
        },
        now=now,
    )
    assert unit is not None
    assert unit.action_duration_sec() == 18


def test_seed_uses_action_duration_not_flat_window():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    now = time.time()
    arc = PlotArc(
        summary="旧书",
        units=[
            InteractionUnit(intent="拂去书脊灰尘，将书从架上取下", status="active", span_polls=2),
            InteractionUnit(intent="翻开信纸读完内容", status="pending", span_polls=2),
        ],
    )
    arc.current_index = 0
    schedule = seed_plot_unit_consumption_queue(
        CharacterRhythmSchedule(),
        now=now,
        plot_arc=arc,
    )
    take, read = schedule.executable_units
    assert take.action_duration_sec() == 18
    assert read.action_duration_sec() == 75
    assert read.window_start >= take.window_end - 0.01


def test_sync_scripts_from_plot_arc():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    arc = PlotArc(
        summary="整理标本",
        units=[
            InteractionUnit(intent="核对蜡膜", status="active", span_polls=2),
            InteractionUnit(intent="归拢记录本", status="pending", span_polls=2),
        ],
    )
    arc.current_index = 0
    active_id = arc.units[0].unit_id
    table = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                open_at=time.time(),
                plot_unit_ids=(active_id,),
                status="pending",
            )
        ]
    )
    changed = table.sync_scripts_from_plot_arc(arc)
    assert changed == 1
    assert "核对蜡膜" in table.executable_units[0].script_text


class _FakeLLM:
    available = False

    def generate_json(self, **kwargs):
        del kwargs
        return ""


def test_rhythm_schedule_poll_skips_llm_when_live_enough():
    director = RhythmScheduleDirector(_FakeLLM())  # type: ignore[arg-type]
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
        DialogueSnapshot,
        SessionRuntimeSnapshot,
        SessionSignals,
        SessionSnapshot,
        build_snapshot_id,
    )

    now = time.time()
    current = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                plot_unit_id=f"p{i}",
                open_at=now + 15,
                reason="keep-me",
                status="pending",
                detail="你继续",
            )
            for i in range(5)
        ],
        version=2,
    )
    snap = SessionSnapshot(
        schema_version=1,
        snapshot_id=build_snapshot_id("p", turn_index=2, generation=0),
        session_id="p",
        signals=SessionSignals(session_id="p", turn_index=2, generation=0),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(user_text=""),
    )
    out = director.run(snap, current=current, force_open_now=False, poll=True)
    assert out.payload.get("action") == "keep"
    assert out.reason == "poll_skip_no_refill"
    assert "interaction_unit_complete" not in out.payload


def test_rhythm_refill_fallback_when_llm_empty():
    director = RhythmScheduleDirector(_FakeLLM())  # type: ignore[arg-type]
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
        DialogueSnapshot,
        SessionRuntimeSnapshot,
        SessionSignals,
        SessionSnapshot,
        build_snapshot_id,
    )

    arc = PlotArc(
        summary="爪印",
        units=[
            InteractionUnit(intent="蹲下看爪印", status="active", span_polls=2),
            InteractionUnit(intent="辨认方向", status="pending", span_polls=2),
        ],
    )
    arc.current_index = 0
    snap = SessionSnapshot(
        schema_version=1,
        snapshot_id=build_snapshot_id("s", turn_index=1, generation=0),
        session_id="s",
        signals=SessionSignals(session_id="s", turn_index=1, generation=0),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(user_text=""),
    )
    out = director.run(
        snap,
        current=CharacterRhythmSchedule(),
        poll=True,
        plot_arc=arc,
    )
    schedule = CharacterRhythmSchedule.from_dict(out.payload.get("schedule"))
    assert schedule.live_unit_count() >= 2
    assert all(e.has_enrichment() for e in schedule.pending_units())
    assert out.payload.get("timeline")


def test_seed_plot_queue_binds_all_pending_units_one_to_one():
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    now = time.time()
    arc = PlotArc(
        summary="开锁扣",
        units=[
            InteractionUnit(intent="书签抵住锁扣", status="active", span_polls=2),
            InteractionUnit(intent="沿横纹缓旋感受阻力", status="pending", span_polls=2),
            InteractionUnit(intent="阻力松动后继续旋开", status="pending", span_polls=2),
            InteractionUnit(intent="核对蜡膜与针尖仍对齐", status="pending", span_polls=2),
        ],
    )
    arc.current_index = 0
    ids = [u.unit_id for u in arc.units]
    schedule = seed_plot_unit_consumption_queue(
        CharacterRhythmSchedule(),
        now=now,
        plot_arc=arc,
    )
    pending = [e for e in schedule.executable_units if e.status == "pending"]
    assert len(pending) == 4
    for entry, uid in zip(sorted(pending, key=lambda e: e.open_at), ids):
        assert entry.plot_unit_id == uid
        assert entry.has_enrichment()


def test_seed_without_plot_arc_does_not_fake_ladder():
    schedule = seed_plot_unit_consumption_queue(
        CharacterRhythmSchedule(),
        now=time.time(),
        plot_arc=None,
    )
    assert schedule.executable_units == []


def test_speak_agenda_gap_and_director_priority():
    rng = random.Random(7)
    gap = sample_booking_gap_sec(rng=rng)
    assert gap >= BOOKING_GAP_MIN_SEC
    now = time.time()
    agenda = CharacterSpeakAgenda()
    agenda.note_event(now)
    char = agenda.add_speak(
        at=now + 8,
        source="character",
        reason="太密",
        plot_unit_id="p1",
        rng=random.Random(1),
    )
    assert char.at >= now + BOOKING_GAP_MIN_SEC
    director = agenda.add_speak(
        at=now + 30,
        source="director",
        reason="导演戳",
        plot_unit_id="p1",
        rng=random.Random(2),
    )
    collide = agenda.add_speak(
        at=director.at,
        source="character",
        reason="撞导演",
        plot_unit_id="p1",
        rng=random.Random(3),
    )
    assert collide.at >= director.at + BOOKING_GAP_MIN_SEC - 0.01
    due = agenda.due_entries(now=max(director.at, char.at) + 1)
    assert due[0].source == "director"


def test_window_consume_pair_via_coordinator():
    from agent.soul.speak.responders.request_driven.directors.coordinator import (
        DirectorCoordinator,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )
    from agent.soul.speak.responders.request_driven.screenwriter import Screenwriter

    now = time.time()
    state = SessionSchedulingState(session_id="win")
    state.plot_arc = PlotArc(
        summary="爪印",
        units=[
            InteractionUnit(intent="蹲下看爪印", status="active", span_polls=2),
            InteractionUnit(intent="辨认方向", status="pending", span_polls=2),
        ],
    )
    state.plot_arc.current_index = 0
    first = state.plot_arc.units[0].unit_id
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                plot_unit_id=first,
                status="pending",
                detail="你蹲下",
                window_start=now - 100,
                window_end=now - 1,
                open_at=now - 100,
            )
        ]
    )
    coordinator = DirectorCoordinator.__new__(DirectorCoordinator)
    coordinator._screenwriter = Screenwriter(llm=None)
    coordinator._maybe_consume_pair_by_window(state)
    assert all(u.unit_id != first for u in state.plot_arc.units)
    assert state.plot_arc.active_unit().intent == "辨认方向"
    assert any("pair_consume: window_end" in n for n in state.notes)


def test_booking_next_plot_consumes_pair():
    from agent.soul.speak.responders.request_driven.character.booking import (
        apply_bookings_to_agenda,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )

    state = SessionSchedulingState(session_id="book")
    state.plot_arc = PlotArc(
        summary="爪印",
        units=[
            InteractionUnit(intent="蹲下看爪印", status="active", span_polls=2),
            InteractionUnit(intent="辨认方向", status="pending", span_polls=2),
        ],
    )
    state.plot_arc.current_index = 0
    first = state.plot_arc.units[0].unit_id
    second = state.plot_arc.units[1].unit_id
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                plot_unit_id=first,
                status="pending",
                detail="你蹲下",
                window_start=time.time(),
                window_end=time.time() + 120,
            )
        ]
    )
    agenda = CharacterSpeakAgenda()
    state.speak_agenda = agenda
    notes = apply_bookings_to_agenda(
        agenda,
        [{"kind": "speak", "at_sec": 40, "reason": "下一对再开口", "plot_unit_id": second}],
        state=state,
    )
    assert any("consume_pair_before_book" in n for n in notes)
    assert state.plot_arc.active_unit().intent == "辨认方向"
    assert agenda.entries[0].source == "character"


def test_mark_schedule_speak_handoff_uses_agenda_origin():
    from agent.soul.speak.responders.request_driven.directors.coordinator import (
        DirectorCoordinator,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
        InteractionUnit,
        PlotArc,
    )
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
        AgendaEntry,
    )

    now = time.time()
    state = SessionSchedulingState(session_id="handoff")
    state.plot_arc = PlotArc(
        summary="核对",
        units=[InteractionUnit(intent="核对蜡膜", status="active", span_polls=2)],
    )
    state.plot_arc.current_index = 0
    active_id = state.plot_arc.units[0].unit_id
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-1",
                open_at=now - 5,
                plot_unit_ids=(active_id,),
                status="pending",
                detail="你核对蜡膜",
                script_text="本拍台本：\n- 核对蜡膜",
            ),
        ]
    )
    entry = AgendaEntry(
        at=now - 1,
        source="director",
        plot_unit_id=active_id,
        reason="导演戳到期",
    )
    coordinator = DirectorCoordinator.__new__(DirectorCoordinator)
    coordinator._mark_schedule_speak_handoff(
        state,
        user_text="",
        turn_index=1,
        reason="agenda_due",
        agenda_entry=entry,
    )
    assert state.pending_character_handoff is not None
    assert state.pending_character_handoff.get("origin") == "director"
    assert state.pending_character_handoff.get("user_text") == ""
    assert state.pending_character_handoff.get("executable_unit_id") == "exec-1"
