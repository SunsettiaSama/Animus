from __future__ import annotations

from agent.soul.speak.responders.request_driven.character.contracts import (
    CharacterReplyRequest,
    NarrativeSnapshot,
)
from agent.soul.speak.responders.request_driven.character.runtime import CharacterRuntime
from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
    RoleContextView,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    build_delivery_plan,
)
from agent.soul.speak.responders.request_driven.responder import SpeakRole
import agent.soul.speak.responders.request_driven.character.runtime as runtime_mod


def _fake_generate(system: str, user_text: str) -> str:
    del system
    return f"[think]ok[/think]\n[emit]reply-for:{user_text[:40]}[/emit]"


def test_user_and_director_triggers_share_character_runtime():
    role = SpeakRole(generate_fn=_fake_generate)
    runtime = CharacterRuntime(speak_role=role)
    view = RoleContextView(session_id="s-dual")
    materials = DynamicLayerMaterials(session_id="s-dual")
    schedule = DynamicLayerSchedule(reason="test")

    class _Bundle:
        pass

    orig_build = runtime_mod.build_turn_system

    def _fake_system(bundle, **kwargs):
        del bundle, kwargs
        return "sys"

    runtime_mod.build_turn_system = _fake_system
    try:
        user_req = CharacterReplyRequest(
            origin="user",
            session_id="s-dual",
            turn_index=1,
            trigger_id="user:s-dual:1",
            user_text="用户来了",
            narrative=NarrativeSnapshot(plot_outline_text="角色大纲A"),
        )
        director_req = CharacterReplyRequest(
            origin="director",
            session_id="s-dual",
            turn_index=2,
            trigger_id="director:exec-9:poll_finish",
            director_cue="（系统：按台本推进本拍演出。）",
            reason="poll_finish",
            narrative=NarrativeSnapshot(plot_outline_text="角色大纲B", director_focus="轻声"),
            executable_unit_id="exec-9",
        )
        plan = build_delivery_plan(segments=[], continuity="finish", turn_index=1)
        user_out = runtime.run(
            user_req,
            bundle=_Bundle(),
            view=view,
            materials=materials,
            schedule=schedule,
            director_plan=plan,
            notes=[],
        )
        director_out = runtime.run(
            director_req,
            bundle=_Bundle(),
            view=view,
            materials=materials,
            schedule=schedule,
            director_plan=plan,
            notes=[],
        )
    finally:
        runtime_mod.build_turn_system = orig_build

    assert user_out.origin == "user"
    assert director_out.origin == "director"
    assert user_out.trigger_id != director_out.trigger_id
    assert "用户" in user_out.raw
    # director 唤醒：cue 不进 generate 用户字；正文入口为空串
    assert "reply-for:" in director_out.raw
    assert any("character_runtime:origin=user" in n for n in user_out.notes)
    assert any("character_runtime:origin=director" in n for n in director_out.notes)
    assert any("character_memory_buffer:占位" in n for n in user_out.notes)
    assert runtime.memory_buffer.linked is False
    assert runtime.memory_buffer.inject_texts() == ()
