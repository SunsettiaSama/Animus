"""角色侧往来账本：沉默合并与真实开口语义。

预约/决策层已按职责分离收敛（预约权归导演），本文件只覆盖账本行为。
"""

from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.character.interaction import (
    export_interaction_record,
    note_character_exchange,
    note_character_think_silence,
    note_pending_user,
    note_user_silence_on_wake,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)


def test_wake_silence_merges_into_one_entry_with_duration():
    """沉默不再逐条占位：同侧连续沉默合并为一条摘要，并给出沉默时长。"""
    state = SessionSchedulingState(session_id="alt")
    assert note_user_silence_on_wake(state) is True
    assert note_user_silence_on_wake(state) is True  # 同一段继续合并计数
    note_character_think_silence(state, reason="还在看爪印，先不开口")
    assert note_user_silence_on_wake(state) is True
    note_character_think_silence(state, reason="心情沉着，继续等")
    rec = export_interaction_record(state)
    # 对白列表不再出现沉默占位行
    assert all("没有说话" not in t for t in rec.recent_turns)
    assert rec.user_silence_count == 3
    assert rec.agent_silence_count == 2
    text = rec.render_for_character()
    assert "你已沉默" in text
    assert "对方已" in text and "没有说话" in text
    # 时长按分钟表达：把用户沉默起点拨回 125 秒前
    data = dict(state.director_cache["character_interaction_record"])
    data["user_silence"] = {"since": time.time() - 125, "count": 3}
    state.director_cache["character_interaction_record"] = data
    rec2 = export_interaction_record(state)
    assert "约 2 分钟" in rec2.render_for_character()


def test_real_speech_ends_silence_segment():
    """真实开口结束对应侧沉默段；角色沉默不再冒充「你最近一句」。"""
    state = SessionSchedulingState(session_id="end")
    note_character_think_silence(state, reason="先不开口")
    note_user_silence_on_wake(state)
    note_character_exchange(state, user_text="在吗", agent_text="在。")
    rec = export_interaction_record(state)
    assert rec.agent_silence_count == 0
    assert rec.user_silence_count == 0
    assert rec.last_agent_text == "在。"
    assert rec.recent_turns[-2:] == ("对方：在吗", "你：在。")


def test_user_hot_path_clears_trailing_silence_marks():
    state = SessionSchedulingState(session_id="hot")
    note_user_silence_on_wake(state)
    note_pending_user(state, user_text="听得到吗")
    rec = export_interaction_record(state)
    assert rec.recent_turns[-1] == "对方：听得到吗"
    assert "对方：【......（没有说话）】" not in rec.recent_turns
    note_pending_user(state, user_text="（系统：按台本推进本拍演出。）")
    assert export_interaction_record(state).recent_turns[-1] == "对方：听得到吗"


def test_legacy_silence_marks_are_cleaned_from_ledger():
    """旧账本里残留的沉默占位行在导出时被清洗，不再进入对白列表。"""
    state = SessionSchedulingState(session_id="legacy")
    state.director_cache["character_interaction_record"] = {
        "recent_turns": [
            "对方：你好？",
            "你：【......（没有说话）】",
            "对方：【......（没有说话）】",
        ],
    }
    rec = export_interaction_record(state)
    assert rec.recent_turns == ("对方：你好？",)
