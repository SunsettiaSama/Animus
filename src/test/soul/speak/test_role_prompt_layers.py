from __future__ import annotations

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.prompt import build_role_prompt


def test_static_and_dynamic_separation_director_schedules_injection():
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
    assert "导演调度" in scheduled.system_extra
