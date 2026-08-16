from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)

from .layers import RolePromptLayers, assemble_role_layers


@dataclass(frozen=True)
class RolePrompt:
    system_extra: str
    user_text: str
    layers: RolePromptLayers | None = None


def build_role_prompt(
    view: RoleContextView,
    *,
    user_text: str,
    materials: DynamicLayerMaterials | None = None,
    schedule: DynamicLayerSchedule | None = None,
    behavior_guide: str = "",
    script_hint: str = "",
    help_observations: tuple[str, ...] = (),
    presence_mood: str = "",
    presence_brief: str = "",
) -> RolePrompt:
    """静态层 +（仅导演调度后的）动态层。未给 schedule 时动态层为空。"""
    mats = materials or DynamicLayerMaterials(session_id=view.session_id)
    sched = schedule or DynamicLayerSchedule(reason="no_director_schedule")
    layers = assemble_role_layers(
        view,
        mats,
        sched,
        user_text=user_text,
        behavior_guide=behavior_guide,
        script_hint=script_hint,
        help_observations=help_observations,
        presence_mood=presence_mood,
        presence_brief=presence_brief,
    )
    return RolePrompt(
        system_extra=layers.render_system_extra(),
        user_text=user_text.strip(),
        layers=layers,
    )
