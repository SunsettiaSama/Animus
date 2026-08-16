from __future__ import annotations

from dataclasses import dataclass

from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
    DynamicLayerMaterials,
    DynamicLayerSchedule,
)
from agent.soul.speak.responders.request_driven.composer.projectors.role_view import (
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
    presence_speak_desire: int | None = None,
    presence_fate_tendency: str = "",
    user_identity: str = "",
    user_activity: str = "",
    interaction_channel: str = "",
    plot_outline_text: str = "",
    plot_flow_text: str = "",
    scene_event: str = "",
    silence_log_text: str = "",
    director_focus: str = "",
    director_intent: str = "",
    director_direction: str = "",
    director_exit: str = "",
    director_detail: str = "",
    director_inner: str = "",
    director_transition: str = "",
    director_stance: str = "",
    interaction_record_text: str = "",
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
        presence_speak_desire=presence_speak_desire,
        presence_fate_tendency=presence_fate_tendency,
        user_identity=user_identity,
        user_activity=user_activity,
        interaction_channel=interaction_channel,
        plot_outline_text=plot_outline_text,
        plot_flow_text=plot_flow_text,
        scene_event=scene_event,
        silence_log_text=silence_log_text,
        director_focus=director_focus,
        director_intent=director_intent,
        director_direction=director_direction,
        director_exit=director_exit,
        director_detail=director_detail,
        director_inner=director_inner,
        director_transition=director_transition,
        director_stance=director_stance,
        interaction_record_text=interaction_record_text,
    )
    return RolePrompt(
        system_extra=layers.render_system_extra(),
        user_text=user_text.strip(),
        layers=layers,
    )
