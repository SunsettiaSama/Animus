from __future__ import annotations

from agent.soul.speak.responders.request_driven.character.context import (
    REMOTE_TEXT_CHANNEL,
    build_narrative_snapshot,
)
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.orchestrator.blocks.system.role import (
    build_role,
)
from agent.soul.speak.responders.request_driven.prompt import build_role_prompt


def test_role_identity_is_remote_text_channel():
    inbound = build_role("inbound")
    proactive = build_role("proactive")
    for text in (inbound, proactive):
        assert "远程" in text
        assert "短消息" in text
        assert "「你」指用户" in text
        assert "「我」指你自己" in text
        assert "只指 NPC" in text
        assert "当面" not in text
        assert "body action" not in text
        assert "(speak)" not in text
    assert "主动发一条短消息" in proactive
    assert "刚发来一条消息" in inbound
    assert "先不回" in inbound


def test_narrative_snapshot_includes_remote_interaction_channel():
    narrative = build_narrative_snapshot(object())
    assert REMOTE_TEXT_CHANNEL in narrative.interaction_channel
    assert "远程" in narrative.interaction_channel
    assert "当面" not in narrative.interaction_channel
    assert "body action" not in narrative.interaction_channel


def test_static_and_dynamic_separation_screenwriter_schedules_injection():
    view = RoleContextView(
        session_id="s",
        history_distilled=("昨天聊过海边",),
        working_turns=(("今天呢", "还好"),),
    )
    materials = DynamicLayerMaterials(
        session_id="s",
        memory_ids=("a", "b"),
        memory_texts=("春天去过海边", "喜欢热茶"),
        share_texts=("想分享一件小事",),
        director_memory_texts=("导演侧检索到的线索",),
    )
    empty = build_role_prompt(view, user_text="嗨", materials=materials)
    assert "对话轨迹" in empty.system_extra
    assert "春天去过海边" not in empty.system_extra
    assert "想分享一件小事" not in empty.system_extra

    scheduled = build_role_prompt(
        view,
        user_text="嗨",
        materials=materials,
        schedule=DynamicLayerSchedule(
            inject_memory=True,
            memory_unit_ids=("a",),
            inject_share=True,
            share_indices=(0,),
            pass_info=True,
            reason="poll_open",
        ),
    )
    assert "春天去过海边" in scheduled.system_extra
    assert "喜欢热茶" not in scheduled.system_extra
    assert "想分享一件小事" in scheduled.system_extra
    assert "导演侧检索到的线索" in scheduled.system_extra
    assert "剧情流传递" in scheduled.system_extra
    assert "记忆卡片" in scheduled.system_extra or "一次性记忆" in scheduled.system_extra
    assert "本轮动态材料" in scheduled.system_extra