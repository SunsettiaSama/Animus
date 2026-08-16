from __future__ import annotations

from typing import Any

from .fate import FateDiceRoll, roll_fate_dice
from .host import DirectorAgentHost, DirectorFrameContext
from .units import (
    AgentDeliveryTraceUnit,
    FateDiceUnit,
    InteractionPlanUnit,
    PollTickUnit,
    PresenceUnit,
    PlotFlowUnit,
    RhythmCardUnit,
    SceneEventUnit,
    UserSilenceUnit,
    UserStageUnit,
)


def build_rhythm_card(
    *,
    typing_active: bool,
    typing_idle: bool,
    push_phase: str,
    brew_queue_depth: int,
    share_wants: bool,
    silence_armed: bool,
    social_armed: str | None,
    speak_gate: str = "",
    user_queue_pending: bool = False,
) -> str:
    parts = [
        f"typing_active={typing_active}",
        f"typing_idle={typing_idle}",
        f"push_phase={push_phase}",
        f"brew_queue_depth={brew_queue_depth}",
        f"share_wants={share_wants}",
        f"silence_armed={silence_armed}",
        f"social_armed={social_armed or ''}",
        f"user_queue_pending={user_queue_pending}",
    ]
    if speak_gate.strip():
        parts.append(f"last_speak_gate={speak_gate.strip()}")
    return "\n".join(parts)


def inject_director_frame(
    state: Any,
    *,
    session_id: str,
    user_text: str = "",
    rhythm_card: str,
    host: DirectorAgentHost | None = None,
    signal_summary: str = "",
    presence_unit: PresenceUnit | None = None,
    poll_tick: PollTickUnit | None = None,
    user_silence: UserSilenceUnit | None = None,
    user_stage: UserStageUnit | None = None,
    scene_event: SceneEventUnit | None = None,
    plot_flow: PlotFlowUnit | None = None,
    delivery_trace: AgentDeliveryTraceUnit | None = None,
) -> DirectorFrameContext:
    """每帧注入节奏/命运骰/编剧剧情流/临场附带；过往帧丢弃。骰为软开口欲。"""
    previous = getattr(state, "fate_speak_desire", None)
    if previous is not None:
        previous = int(previous)
    if host is not None:
        frame = host.begin_frame(
            session_id=session_id,
            rhythm_card=rhythm_card,
            user_text=user_text,
            signal_summary=signal_summary,
            previous_fate=previous,
            memory_cards=None,
        )
    else:
        fate = roll_fate_dice(previous=previous)
        frame = DirectorFrameContext(
            session_id=session_id.strip(),
            rhythm_card=rhythm_card,
            fate=fate,
            user_text=user_text,
            signal_summary=signal_summary,
        )
    state.fate_speak_desire = int(frame.fate.roll)
    blocks = [frame.render()]
    if user_silence is not None:
        rendered = user_silence.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["user_silence"] = rendered
    if presence_unit is not None:
        rendered = presence_unit.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["presence_unit"] = rendered
    if plot_flow is not None:
        rendered = plot_flow.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["plot_flow_unit"] = rendered
    if user_stage is not None:
        rendered = user_stage.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["user_stage"] = rendered
    if scene_event is not None:
        rendered = scene_event.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["scene_event"] = rendered
    if poll_tick is not None:
        rendered = poll_tick.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["poll_tick"] = rendered
    if delivery_trace is not None:
        rendered = delivery_trace.render().strip()
        if rendered:
            blocks.append(rendered)
            state.director_cache["agent_delivery_trace_block"] = rendered
    state.director_cache["frame_prompt"] = "\n\n".join(blocks)
    state.director_cache["fate_dice"] = {
        "roll": frame.fate.roll,
        "speak_desire": frame.fate.speak_desire,
        "tendency": frame.fate.tendency,
        "previous": previous,
    }
    state.director_cache["rhythm_card"] = rhythm_card
    return frame


def append_frame_prompt(prompt: str, snapshot) -> str:
    decisions = getattr(getattr(snapshot, "orchestrator", None), "director_decisions", None) or {}
    block = ""
    if isinstance(decisions, dict):
        block = str(decisions.get("frame_prompt") or "").strip()
    if not block:
        return prompt
    return f"{prompt.rstrip()}\n\n{block}"


__all__ = [
    "DirectorAgentHost",
    "DirectorFrameContext",
    "AgentDeliveryTraceUnit",
    "FateDiceRoll",
    "FateDiceUnit",
    "InteractionPlanUnit",
    "MemoryBufferCardUnit",
    "PollTickUnit",
    "PresenceUnit",
    "PlotFlowUnit",
    "RhythmCardUnit",
    "SceneEventUnit",
    "UserSilenceUnit",
    "UserStageUnit",
    "append_frame_prompt",
    "build_rhythm_card",
    "inject_director_frame",
    "roll_fate_dice",
]
