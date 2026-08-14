from __future__ import annotations

from typing import Any

from .fate import FateDiceRoll, roll_fate_dice
from .host import DirectorAgentHost, DirectorFrameContext
from .units import FateDiceUnit, RhythmCardUnit


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
) -> DirectorFrameContext:
    """每帧注入节奏/命运骰卡片；过往帧丢弃。骰不改 speak_gate。"""
    if host is not None:
        frame = host.begin_frame(
            session_id=session_id,
            rhythm_card=rhythm_card,
            user_text=user_text,
            signal_summary=signal_summary,
        )
    else:
        fate = roll_fate_dice()
        frame = DirectorFrameContext(
            session_id=session_id.strip(),
            rhythm_card=rhythm_card,
            fate=fate,
            user_text=user_text,
            signal_summary=signal_summary,
        )
    state.director_cache["frame_prompt"] = frame.render()
    state.director_cache["fate_dice"] = {
        "roll": frame.fate.roll,
        "tendency": frame.fate.tendency,
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
    "FateDiceRoll",
    "FateDiceUnit",
    "RhythmCardUnit",
    "append_frame_prompt",
    "build_rhythm_card",
    "inject_director_frame",
    "roll_fate_dice",
]
