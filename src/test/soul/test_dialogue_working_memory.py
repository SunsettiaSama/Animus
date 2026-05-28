from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.soul.presence.config import (
    DIALOGUE_WORKING_MEMORY_MAX_CHUNKS,
    DIALOGUE_WORKING_MEMORY_WINDOW_SEC,
)
from agent.soul.life.experience import LifeExperienceStack
from agent.soul.life.experience.dialogue import (
    DialogueState,
    DialogueWorkingMemory,
)
from agent.soul.life.experience.dialogue.session import render_session_transcript
from agent.soul.presence.service import PresenceService


def _ts(offset_sec: float = 0.0) -> datetime:
    base = datetime(2026, 5, 25, 12, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_sec)


def test_config_defaults():
    assert DIALOGUE_WORKING_MEMORY_WINDOW_SEC == 5.0
    assert DIALOGUE_WORKING_MEMORY_MAX_CHUNKS == 4


def test_working_memory_keeps_chunks_within_five_seconds():
    wm = DialogueWorkingMemory()
    wm.append_turn("第一�?, "回应一", now=_ts(0))
    wm.append_turn("第二�?, "回应�?, now=_ts(2))

    text = wm.render(now=_ts(4.5))
    assert "第一�? in text
    assert "回应�? in text
    assert wm.chunk_count == 2


def test_working_memory_drops_chunks_older_than_window():
    wm = DialogueWorkingMemory()
    wm.append_turn("旧轮", "旧回�?, now=_ts(0))
    wm.append_turn("新轮", "新回�?, now=_ts(4))

    text = wm.render(now=_ts(6))
    assert "旧轮" not in text
    assert "新轮" in text
    assert wm.chunk_count == 1


def test_working_memory_truncates_to_max_chunks():
    wm = DialogueWorkingMemory(max_chunks=4)
    for index in range(6):
        wm.append_turn(f"q{index}", f"a{index}", now=_ts(index))

    text = wm.render(now=_ts(5))
    assert "q0" not in text
    assert "q1" not in text
    assert "q5" in text
    assert wm.chunk_count == 4


def test_dialogue_state_records_turn_as_one_chunk():
    state = DialogueState.open("tao")
    state.record_turn(user_text="你好", agent_text="�?, now=_ts(1))
    assert len(state.session.turns) == 1
    assert state.working_memory.chunk_count == 1
    assert "你好" in state.working_memory_text(now=_ts(1))
    assert "�? in state.working_memory_text(now=_ts(1))


def test_pipeline_syncs_working_memory_to_presence_cognition(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = LifeExperienceStack(life_dir=life_dir)

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="架构怎么�?,
        agent_text="分三�?,
        now=_ts(1),
    )
    snap = presence.snapshot("tao")
    assert "架构怎么�? in snap.state.cognition.working_memory
    assert "分三�? in snap.state.cognition.working_memory

    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="再说细一�?,
        agent_text="好的",
        now=_ts(7),
    )
    snap = presence.snapshot("tao")
    assert "架构怎么�? not in snap.state.cognition.working_memory
    assert "再说细一�? in snap.state.cognition.working_memory


def test_session_keeps_all_turns_while_working_memory_truncates():
    state = DialogueState.open("tao")
    for index in range(6):
        state.record_turn(
            user_text=f"q{index}",
            agent_text=f"a{index}",
            now=_ts(index),
        )
    assert len(state.session.turns) == 6
    assert state.working_memory.chunk_count == 4
    transcript = render_session_transcript(state.session)
    assert "q0" in transcript
    assert "q5" in transcript


def test_close_uses_full_transcript_as_memory_fuel(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    pipeline = LifeExperienceStack(life_dir=life_dir)

    for index in range(3):
        pipeline.dialogue.record_dialogue_turn(
            presence,
            session_id="tao",
            user_text=f"q{index}",
            agent_text=f"a{index}",
            now=_ts(index),
        )
    from agent.soul.presence.share_desire import StaticStatePatch

    presence.patch_static(
        "tao",
        StaticStatePatch(affect="专注", perception="对话进行�?),
    )
    unit = pipeline.dialogue.close_dialogue(presence, "tao")
    assert unit is not None
    assert "q0" in unit.situation.perception
    assert "q2" in unit.situation.perception
    assert "a2" in unit.situation.perception


def test_pipeline_exposes_dialogue_state(tmp_path):
    pipeline = LifeExperienceStack(life_dir=str(tmp_path))
    presence = PresenceService(life_dir=str(tmp_path))
    pipeline.dialogue.record_dialogue_turn(
        presence,
        session_id="tao",
        user_text="q",
        agent_text="a",
        now=_ts(0),
    )
    state = pipeline.dialogue.state("tao")
    assert state is not None
    assert state.session_id == "tao"
    assert len(state.session.turns) == 1
