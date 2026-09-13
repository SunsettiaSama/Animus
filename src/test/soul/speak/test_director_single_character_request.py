"""导演每拍只向角色请求一次：due + poll_finish 不得双推。"""

from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
    CharacterRhythmSchedule,
    ExecutableUnit,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.interaction_plan import (
    InteractionUnit,
    PlotArc,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
    StateStore,
)
from agent.soul.speak.responders.request_driven.directors.coordinator import (
    DirectorCoordinator,
)
from agent.soul.speak.responders.request_driven.orchestrator.runtime.ingress import (
    IngressEvent,
)
from agent.soul.speak.responders.request_driven.orchestrator.runtime.orchestrator_thread import (
    OrchestratorThread,
)


def test_replace_preserves_reserved_status():
    """节奏 keep/patch 不得把已交接的 reserved 冲回 pending，否则会重复请求角色。"""
    now = time.time()
    current = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                status="reserved",
                plot_unit_ids=("iu-1",),
                focus="看泥径",
            ),
            ExecutableUnit(
                unit_id="exec-b",
                open_at=now + 30,
                status="pending",
                plot_unit_ids=("iu-2",),
            ),
        ]
    )
    nxt = current.replace_from_director_payload(
        {
            "executable_units": [
                {
                    "unit_id": "exec-a",
                    "open_at": now,
                    "status": "pending",
                    "plot_unit_ids": ["iu-1"],
                    "focus": "看泥径",
                },
                {
                    "unit_id": "exec-b",
                    "open_at": now + 30,
                    "status": "pending",
                    "plot_unit_ids": ["iu-2"],
                },
            ]
        },
        poll_seq=2,
        now=now,
    )
    by_id = {e.unit_id: e for e in nxt.executable_units}
    assert by_id["exec-a"].status == "reserved"
    assert by_id["exec-b"].status == "pending"
    assert nxt.due_units(now=now) == []


def test_dispatch_due_handoff_only_agenda_not_window():
    """角色主动开口只认 agenda due；仅有 rhythm window due 时不交角色。"""
    store = StateStore()
    state = store.session("live:wait-open")
    now = time.time()
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                window_start=now - 1,
                status="pending",
                plot_unit_ids=("iu-1",),
            )
        ]
    )
    state.director_cache["narrative_opening_ready"] = True
    coord = object.__new__(DirectorCoordinator)
    coord._state_store = store

    class _Snap:
        class _Signals:
            turn_index = 0

        signals = _Signals()

    class _Builder:
        def build(self, session_id: str):
            del session_id
            return _Snap()

    coord._snapshot_builder = _Builder()
    assert coord.dispatch_due_handoff("live:wait-open") is None

    state.speak_agenda.add_speak(
        at=now - 1,
        source="character",
        reason="预约到点",
        plot_unit_id="iu-1",
        enforce=False,
    )
    out = coord.dispatch_due_handoff("live:wait-open")
    assert out is not None
    assert out.get("reason") == "agenda_due"


def test_dispatch_due_handoff_waits_for_screenwriter_opening():
    store = StateStore()
    state = store.session("live:wait-open2")
    now = time.time()
    state.speak_agenda.add_speak(
        at=now - 1,
        source="character",
        reason="预约到点",
        plot_unit_id="iu-1",
        enforce=False,
    )
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                window_start=now - 1,
                status="pending",
                plot_unit_ids=("iu-1",),
            )
        ]
    )
    coord = object.__new__(DirectorCoordinator)
    coord._state_store = store

    class _Snap:
        class _Signals:
            turn_index = 0

        signals = _Signals()

    class _Builder:
        def build(self, session_id: str):
            del session_id
            return _Snap()

    coord._snapshot_builder = _Builder()
    assert coord.dispatch_due_handoff("live:wait-open2") is None
    assert any("hold_handoff_wait_opening" in n for n in state.notes)
    state.director_cache["narrative_opening_ready"] = True
    out = coord.dispatch_due_handoff("live:wait-open2")
    assert out is not None
    assert out.get("executable_unit_id") == "exec-a"


def test_mark_reserved_is_idempotent():
    now = time.time()
    schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                status="reserved",
                plot_unit_ids=("iu-1",),
            ),
        ]
    )
    again = schedule.mark_reserved("exec-a")
    assert again is not None
    assert again.status == "reserved"


def test_mark_handoff_skips_when_reserved():
    state = SessionSchedulingState(session_id="s-once")
    now = time.time()
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-a",
                open_at=now - 1,
                status="reserved",
                plot_unit_ids=("iu-1",),
                script_text="看爪印",
            ),
            ExecutableUnit(
                unit_id="exec-b",
                open_at=now - 1,
                status="pending",
                plot_unit_ids=("iu-2",),
                script_text="再看一次",
            ),
        ]
    )
    state.plot_arc = PlotArc(
        summary="泥径",
        evidence="雨后",
        units=[InteractionUnit(intent="看爪印", evidence="泥", span_polls=2)],
        current_index=0,
        revised_at=now,
        version=1,
    )

    coord = object.__new__(DirectorCoordinator)
    DirectorCoordinator._mark_schedule_speak_handoff(
        coord,
        state,
        user_text="",
        turn_index=0,
        reason="poll_finish",
    )
    assert state.pending_character_handoff is None
    assert any("skip_handoff_already_reserved" in n for n in state.notes)


def test_poll_tick_notifies_character_handoff_once():
    calls: list[dict] = []

    class _Coord:
        def __init__(self) -> None:
            self._pending = {"trigger_id": "due-1", "executable_unit_id": "exec-a"}
            self.ticks = 0

        def dispatch_due_handoff(self, session_id: str):
            del session_id
            return dict(self._pending)

        def take_character_handoff(self, session_id: str):
            del session_id
            if self._pending is None:
                return None
            out = dict(self._pending)
            self._pending = None
            return out

        def peek_character_handoff(self, session_id: str):
            del session_id
            return dict(self._pending) if self._pending else None

        def on_poll_tick(self, session_id: str, *, trigger: str = "idle"):
            del session_id, trigger
            self.ticks += 1
            # 模拟旧 bug：poll_finish 再塞一次 pending
            self._pending = {"trigger_id": "poll-2", "executable_unit_id": "exec-b"}

    coord = _Coord()
    store = StateStore()
    thread = OrchestratorThread(
        state_store=store,
        coordinator=coord,  # type: ignore[arg-type]
        on_character_handoff=lambda sid, h: calls.append({"sid": sid, "handoff": h}),
    )
    thread._handle_event(
        IngressEvent(kind="poll_tick", session_id="live:once", trigger="idle")
    )
    assert coord.ticks == 1
    assert len(calls) == 1
    assert calls[0]["handoff"]["trigger_id"] == "due-1"
    assert store.session("live:once").pending_character_handoff is None
    assert any(
        "drop_duplicate_pending_after_due_notify" in n
        for n in store.session("live:once").notes
    )


def _make_speak_service():
    from unittest.mock import MagicMock

    from agent.soul.speak.llm.engine import SpeakLLMEngine
    from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
    from agent.soul.speak.service import SpeakService
    from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
    from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound

    class _FakeLLM:
        def generate_messages(self, messages):
            del messages
            return "<speak>收到</speak>"

        def stream_generate_messages(self, messages):
            del messages
            yield "<speak>收到</speak>"

    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    presence.snapshot.return_value = snap
    return SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(_FakeLLM()),
        orchestrator=SpeakOrchestrator(soul, presence),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )


def test_abort_proactive_handoff_releases_reserved_and_rearms():
    service = _make_speak_service()
    sid = "live:abort"
    state = service._state_store.session(sid)
    now = time.time()
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-stuck",
                open_at=now - 1,
                status="reserved",
                plot_unit_ids=("iu-1",),
            )
        ]
    )
    armed = []

    class _Coord:
        def on_delivery_done(self, session_id: str) -> None:
            armed.append(session_id)

    service._director_coordinator = _Coord()
    service._abort_proactive_handoff(
        sid,
        None,
        executable_unit_id="exec-stuck",
        reason="origin_not_proactive",
    )
    assert state.character_rhythm_schedule.executable_units[0].status == "pending"
    assert armed == [sid]
    assert any("abort origin_not_proactive" in n for n in state.notes)


def test_execute_booked_handoff_reaches_character(monkeypatch):
    """预约 origin=booked 且无用户原文时，必须真正进角色生成，不能静默丢掉。"""
    from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
        build_delivery_plan,
    )

    service = _make_speak_service()
    sid = "live:booked"
    state = service._state_store.session(sid)
    now = time.time()
    state.character_rhythm_schedule = CharacterRhythmSchedule(
        executable_units=[
            ExecutableUnit(
                unit_id="exec-booked",
                open_at=now - 1,
                status="reserved",
                plot_unit_ids=("iu-1",),
                detail="你从架上抽出一本墨绿布面书",
            )
        ]
    )
    called: list[str] = []

    class _EmptyParsed:
        def to_dict(self):
            return {}

        session_state = ""

    paced = build_delivery_plan(
        segments=[],
        continuity="finish",
        plan_id="empty",
        turn_index=1,
    )
    monkeypatch.setattr(service, "_director_must_yield_to_user", lambda *_a, **_k: False)
    monkeypatch.setattr(service._session_manager, "is_pushing", lambda *_a, **_k: False)
    monkeypatch.setattr(service, "_refresh_compose_manager_director_meta", lambda *_a, **_k: None)
    monkeypatch.setattr(service, "_compose_bundle", lambda *_a, **_k: object())
    monkeypatch.setattr(
        service,
        "_run_booked_character_reply",
        lambda **kwargs: (
            called.append(kwargs["request"].origin)
            or ("", _EmptyParsed(), paced, True, None)
        ),
    )
    service._director_coordinator = object()
    service._execute_character_handoff(
        sid,
        {
            "origin": "booked",
            "session_id": sid,
            "turn_index": 1,
            "trigger_id": "booked:exec-booked:agenda_due",
            "user_text": "",
            "director_cue": "",
            "reason": "agenda_due",
            "executable_unit_id": "exec-booked",
            "kind": "silence",
        },
    )
    assert called == ["booked"]
    assert not any("empty_user_text" in n for n in state.notes)


