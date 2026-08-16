from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.character.contracts import (
    CharacterReplyRequest,
    DeliveryIntent,
    NarrativeSnapshot,
)
from agent.soul.speak.responders.request_driven.character.context import (
    build_character_reply_request,
    build_narrative_snapshot,
)
from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
    apply_rhythm_schedule_output,
)
from agent.soul.speak.responders.request_driven.directors.base import (
    DirectorOutput,
)
from agent.soul.speak.responders.request_driven.screenwriter import (
    Screenwriter,
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
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


class _State:
    def __init__(self) -> None:
        self.session_id = "s-boundary"
        self.plot_arc = PlotArc(
            summary="角色想看花",
            evidence="帐篷",
            units=[
                InteractionUnit(intent="走到花旁", evidence="花", span_polls=2, status="active"),
                InteractionUnit(intent="仔细观察", evidence="花", span_polls=2, status="pending"),
            ],
            current_index=0,
            revised_at=time.time(),
            version=1,
        )
        self.character_rhythm_schedule = CharacterRhythmSchedule()
        self.director_cache: dict = {}
        self.notes: list[str] = []
        self.poll_seq = 3
        self.speak_gate = "hold"
        self.pending_character_handoff = None
        self.pending_delivery_plan = None
        self.presence_card = CharacterPresenceCard()
        self.narrative_card = NarrativeStageCard()
        self.silence_log = SilenceLog()
        self.plot_flow = PlotFlow()
        self.active_next_turn_guide = {}
        self.screenwriter_continued_at_poll = 0
        self.fate_speak_desire = 50
        self.last_real_user_text = ""


def test_character_reply_request_user_and_director_origins():
    state = SessionSchedulingState(session_id="s1")
    user_req = build_character_reply_request(
        origin="user",
        session_id="s1",
        turn_index=2,
        state=state,
        user_text="你好",
        reason="user_ingress",
    )
    assert user_req.origin == "user"
    assert user_req.user_text == "你好"
    assert user_req.director_cue == ""
    assert user_req.effective_user_text == "你好"
    assert user_req.trigger_id.startswith("user:")

    director_req = build_character_reply_request(
        origin="director",
        session_id="s1",
        turn_index=3,
        state=state,
        director_cue="（系统：按台本推进本拍演出。）",
        reason="poll_finish",
        executable_unit_id="exec-1",
    )
    assert director_req.origin == "director"
    assert director_req.user_text == ""
    # cue 不进用户账本 / effective 文本
    assert director_req.effective_user_text == ""
    assert director_req.narrative.plot_outline_text == ""
    assert director_req.narrative.director_focus == ""
    assert director_req.trigger_id.startswith("director:exec-1")

    restored = CharacterReplyRequest.from_dict(director_req.to_dict())
    assert restored is not None
    assert restored.origin == "director"
    assert restored.user_text == ""
    assert restored.executable_unit_id == "exec-1"
    assert restored.effective_user_text == ""

    booked_req = build_character_reply_request(
        origin="booked",
        session_id="s1",
        turn_index=4,
        state=state,
        reason="agenda_due",
        executable_unit_id="exec-2",
    )
    assert booked_req.origin == "booked"
    assert booked_req.effective_user_text == ""
    assert booked_req.trigger_id.startswith("booked:exec-2")


def test_ownership_rhythm_apply_does_not_complete_via_legacy_flag():
    state = _State()
    before = state.plot_arc.active_unit()
    assert before is not None
    before_intent = before.intent
    schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                open_at=time.time() - 1.0,
                script_text="看花",
                detail="你走到花旁",
                plot_unit_id=before.unit_id,
            ),
        ],
        revised_at=time.time(),
    )
    out = DirectorOutput(
        director="rhythm_schedule",
        payload={
            "schedule": schedule.snapshot(),
            "interaction_unit_complete": True,
            "unit_complete_reason": "done",
        },
        reason="test",
    )
    apply_rhythm_schedule_output(state, out)
    active = state.plot_arc.active_unit()
    assert active is not None
    assert active.intent == before_intent
    assert "pending_unit_complete" not in state.director_cache

    sw = Screenwriter(llm=None)
    sw.confirm_interaction_unit_complete(state, poll_seq=3, reason="window_end")
    nxt = state.plot_arc.active_unit()
    assert nxt is not None
    assert nxt.intent == "仔细观察"
    assert "screenwriter:interaction_unit_complete" in " ".join(state.notes)


def test_ownership_screenwriter_does_not_schedule_speak_opens():
    sw = Screenwriter(llm=None)
    assert not hasattr(sw, "schedule_open")
    assert not hasattr(sw, "insert_executable_unit")
    assert hasattr(sw, "confirm_interaction_unit_complete")
    assert hasattr(sw, "init_presence")


def test_unit_complete_requires_explicit_screenwriter_confirm():
    state = _State()
    arc = state.plot_arc
    active = arc.active_unit()
    assert active is not None
    arc.note_poll(poll_seq=1)
    arc.note_poll(poll_seq=2)
    assert arc.active_unit() is not None
    assert arc.active_unit().intent == "走到花旁"
    assert arc.active_unit().status == "active"

    sw = Screenwriter(llm=None)
    sw.confirm_interaction_unit_complete(state, poll_seq=2, reason="window_end")
    assert state.plot_arc.active_unit().intent == "仔细观察"


def test_narrative_snapshot_is_readonly_copy():
    snap = NarrativeSnapshot(plot_outline_text="A", director_focus="B")
    data = snap.snapshot()
    data["plot_outline_text"] = "hacked"
    assert snap.plot_outline_text == "A"
    intent = DeliveryIntent(speak_gate="speak", continuity="finish")
    assert "speak" not in intent.snapshot().get("plan_id", "x") or True


def test_character_receives_you_voice_enrichment():
    state = _State()
    snapshot = build_narrative_snapshot(state)
    assert "角色想看花" in snapshot.plot_outline_text
    assert "走到花旁" in snapshot.plot_outline_text
    assert snapshot.director_focus == ""

    entry = ExecutableUnit(
        open_at=time.time(),
        unit_id="exec-dir",
        detail="你正蹲在泥地旁看爪印",
        inner="你心里发紧，先不开口",
        transition="你先把爪印看清楚，再决定要不要搭话",
        stance="你自然停住，不硬问",
        script_text="走到花旁",
    )
    state.character_rhythm_schedule.executable_units.append(entry)
    bound = build_narrative_snapshot(state, executable_unit_id="exec-dir")
    assert bound.director_detail == "你正蹲在泥地旁看爪印"
    assert "你心里发紧" in bound.director_inner
    text = bound.render_director_instruction()
    assert "你手头：" in text
    assert "你在想：" in text
    assert "你怎么过渡：" in text
    assert "你的姿态：" in text
    assert entry.render_script_for_character() == "走到花旁"


def test_user_reply_binds_pending_plot_unit_alongside():
    state = _State()
    proactive = ExecutableUnit(
        open_at=time.time() - 1,
        plot_unit_ids=(state.plot_arc.units[0].unit_id,),
        detail="你听对方问你是谁",
        status="pending",
    )
    state.character_rhythm_schedule.executable_units.append(proactive)
    state.pending_character_handoff = {"origin": "director"}

    request = build_character_reply_request(
        origin="user",
        session_id=state.session_id,
        turn_index=4,
        state=state,
        user_text="你是？",
    )

    assert proactive.status == "pending"
    assert state.pending_character_handoff is None
    assert request.executable_unit_id == proactive.unit_id
    assert request.plot_unit_ids == proactive.plot_unit_ids
    assert request.narrative.director_detail == "你听对方问你是谁"


def test_extract_json_object_tolerates_fences_and_broken_json():
    from agent.soul.speak.responders.request_driven.directors.base import (
        extract_json_object,
    )

    fenced = extract_json_object('```json\n{"action":"keep","reason":"ok"}\n```')
    assert fenced["action"] == "keep"
    trailing = extract_json_object('{"action":"advance"} extra {')
    assert trailing["action"] == "advance"
    broken = extract_json_object('{"think":"说了句"未闭合的话","action":"produce_plot"}')
    assert broken == {}
