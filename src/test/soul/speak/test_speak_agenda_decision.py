from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.character.booking import (
    apply_bookings_to_agenda,
)
from agent.soul.speak.responders.request_driven.character.book_poll import (
    maybe_poll_character_book,
    should_poll_character_book,
)
from agent.soul.speak.responders.request_driven.character.booked_path import (
    decide_booked_turn,
)
from agent.soul.speak.responders.request_driven.character.decision import (
    HotTurnDecision,
    decide_hot_turn,
    write_hot_delay_booking,
)
from agent.soul.speak.responders.request_driven.character.interaction import (
    export_interaction_record,
    note_character_think_silence,
    note_pending_user,
    note_user_silence_on_wake,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.speak_agenda import (
    BOOKING_GAP_MIN_SEC,
    CharacterSpeakAgenda,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


class _DecisionLLM:
    available = True

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.calls = 0

    def generate_json(self, **kwargs):
        del kwargs
        self.calls += 1
        return self._payload


def test_decide_hot_turn_three_way_actions():
    llm = _DecisionLLM(
        '{"doing":"看爪印","mood":"沉着","action":"silence",'
        '"reason":"先把手头事做完","flush_body":"你继续蹲着看泥印"}'
    )
    decision = decide_hot_turn(
        llm,
        session_id="s1",
        turn_index=1,
        user_text="在干嘛",
        plot_intent="蹲下看爪印",
        rhythm_enrichment="你手头：泥地爪印",
    )
    assert decision.action == "silence"
    assert decision.will_speak is False
    assert "先不开口" in decision.flush_text or "不开口" in decision.flush_text
    assert "<speak>" in decision.flush_text
    assert "<body action>" not in decision.flush_text


def test_decide_hot_turn_fallback_speaks_on_user_hot_path():
    decision = decide_hot_turn(
        None,
        session_id="s1",
        user_text="你在干嘛",
    )
    assert decision.action == "speak"
    assert decision.will_speak is True
    assert "要开口" in decision.flush_text


def test_hot_delay_writes_agenda_immediately():
    llm = _DecisionLLM(
        '{"doing":"编竹","mood":"稳","action":"delay",'
        '"reason":"先把手头收一收","flush_body":"你把竹篾搁稳",'
        '"at_sec":8}'
    )
    decision = decide_hot_turn(
        llm,
        session_id="s1",
        user_text="看我干什么",
    )
    assert decision.action == "delay"
    state = SessionSchedulingState(session_id="delay")
    state.speak_agenda = CharacterSpeakAgenda()
    state.speak_agenda.note_event(time.time())
    note = write_hot_delay_booking(state, decision, plot_unit_id="iu-1")
    assert note.startswith("hot_delay_book:")
    assert state.speak_agenda.entries
    entry = state.speak_agenda.entries[0]
    assert entry.source == "character"
    assert entry.kind == "speak"
    assert entry.at >= state.speak_agenda.last_event_at + BOOKING_GAP_MIN_SEC - 0.01


def test_hot_delay_defaults_at_sec_to_gap():
    decision = HotTurnDecision(
        action="delay",
        reason="稍后回",
        flush_body="你点了下头",
        at_sec=0.0,
    )
    state = SessionSchedulingState(session_id="gap")
    state.speak_agenda = CharacterSpeakAgenda()
    write_hot_delay_booking(state, decision, now=1000.0)
    assert state.speak_agenda.entries[0].at >= 1000.0 + BOOKING_GAP_MIN_SEC - 0.01


def test_booked_turn_cannot_delay_again():
    llm = _DecisionLLM(
        '{"doing":"翻页","mood":"静","action":"delay",'
        '"reason":"再等等","flush_body":"你继续翻"}'
    )
    decision = decide_booked_turn(
        llm,
        session_id="s1",
        origin="booked",
        plot_intent="翻页",
    )
    assert decision.action == "silence"
    assert decision.will_speak is False


def test_book_poll_skips_under_threshold():
    state = SessionSchedulingState(session_id="poll")
    state.interaction_exchange_count = 1
    state.character_book_polled_at_exchange = 0
    assert should_poll_character_book(state) is False
    out = maybe_poll_character_book(None, state, session_id="poll", turn_index=1)
    assert out["polled"] is False


def test_book_poll_asks_when_rounds_met():
    state = SessionSchedulingState(session_id="poll-k")
    state.interaction_exchange_count = 3
    state.character_book_polled_at_exchange = 0
    assert should_poll_character_book(state) is True
    llm = _DecisionLLM(
        '{"should_book":true,"at_sec":30,"reason":"过一会再开口","plot_unit_id":""}'
    )
    out = maybe_poll_character_book(llm, state, session_id="poll-k", turn_index=3)
    assert out["polled"] is True
    assert out["should_book"] is True
    assert state.speak_agenda.entries
    assert state.character_book_polled_at_exchange == 3


def test_wake_silence_alternates_with_character_think():
    state = SessionSchedulingState(session_id="alt")
    assert note_user_silence_on_wake(state) is True
    assert note_user_silence_on_wake(state) is False  # 不叠两条
    note_character_think_silence(state, reason="还在看爪印，先不开口")
    assert note_user_silence_on_wake(state) is True
    note_character_think_silence(state, reason="心情沉着，继续等")
    rec = export_interaction_record(state)
    turns = list(rec.recent_turns)
    assert turns[0] == "对方：【......（没有说话）】"
    assert turns[1] == "你：【......（没有说话）】"
    assert turns[2] == "对方：【......（没有说话）】"
    assert turns[3] == "你：【......（没有说话）】"
    text = rec.render_for_character()
    assert "对方：【......（没有说话）】" in text
    assert "你：【......（没有说话）】" in text


def test_user_hot_path_clears_trailing_silence_marks():
    state = SessionSchedulingState(session_id="hot")
    note_user_silence_on_wake(state)
    note_pending_user(state, user_text="听得到吗")
    rec = export_interaction_record(state)
    assert rec.recent_turns[-1] == "对方：听得到吗"
    assert "对方：【......（没有说话）】" not in rec.recent_turns
    note_pending_user(state, user_text="（系统：按台本推进本拍演出。）")
    assert export_interaction_record(state).recent_turns[-1] == "对方：听得到吗"


def test_apply_bookings_yields_to_director_stamp():
    now = time.time()
    agenda = CharacterSpeakAgenda()
    agenda.note_event(now)
    agenda.add_speak(
        at=now + 40,
        source="director",
        reason="导演先开口",
        plot_unit_id="p1",
        enforce=False,
    )
    apply_bookings_to_agenda(
        agenda,
        [{"kind": "speak", "at_sec": 40, "reason": "角色也约这时", "plot_unit_id": "p1"}],
        now=now,
    )
    character = [e for e in agenda.entries if e.source == "character"][0]
    director = [e for e in agenda.entries if e.source == "director"][0]
    assert character.at >= director.at + BOOKING_GAP_MIN_SEC - 0.01


def test_turn_decision_dataclass_flush_defaults():
    d = HotTurnDecision(action="speak", reason="回一句", flush_body="")
    assert "要开口" in d.flush_text
    assert "回一句" in d.flush_text
