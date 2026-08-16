from __future__ import annotations

__all__ = [
    "DIRECTOR_VOICE",
    "DirectorLLMCaller",
    "DirectorOutput",
    "DirectorCoordinator",
    "OutlineDirector",
    "UserIntentDirector",
    "TurnDeliveryDirector",
    "SpeakGateDirector",
    "RhythmScheduleDirector",
    "apply_rhythm_schedule_output",
    "ModuleInjectDirector",
    "apply_presence_card_output",
    "NextTurnGuide",
    "NextTurnGuideDirector",
    "DirectorThinkCompressor",
    "DIRECTOR_THINK_COMPRESS_RULES",
    "SocialArmDirector",
    "InterruptDirector",
    "PollScheduler",
    "fallback_director_output",
]


def __getattr__(name: str):
    if name == "DIRECTOR_VOICE":
        from .base import DIRECTOR_VOICE

        return DIRECTOR_VOICE
    if name in ("DirectorLLMCaller", "DirectorOutput"):
        from .base import DirectorLLMCaller, DirectorOutput

        return {"DirectorLLMCaller": DirectorLLMCaller, "DirectorOutput": DirectorOutput}[name]
    if name == "DirectorCoordinator":
        from .coordinator import DirectorCoordinator

        return DirectorCoordinator
    if name == "OutlineDirector":
        from .outline import OutlineDirector

        return OutlineDirector
    if name == "UserIntentDirector":
        from .user_intent import UserIntentDirector

        return UserIntentDirector
    if name == "TurnDeliveryDirector":
        from .turn_delivery import TurnDeliveryDirector

        return TurnDeliveryDirector
    if name == "SpeakGateDirector":
        from .speak_gate import SpeakGateDirector

        return SpeakGateDirector
    if name in ("RhythmScheduleDirector", "apply_rhythm_schedule_output"):
        from .rhythm_schedule import RhythmScheduleDirector, apply_rhythm_schedule_output

        return {
            "RhythmScheduleDirector": RhythmScheduleDirector,
            "apply_rhythm_schedule_output": apply_rhythm_schedule_output,
        }[name]
    if name == "ModuleInjectDirector":
        from .module_inject import ModuleInjectDirector

        return ModuleInjectDirector
    if name in ("SocialArmDirector", "InterruptDirector"):
        from . import domain

        return getattr(domain, name)
    if name == "apply_presence_card_output":
        from .presence_card import apply_presence_card_output

        return apply_presence_card_output
    if name in ("NextTurnGuide", "NextTurnGuideDirector"):
        from .next_turn_guide import NextTurnGuide, NextTurnGuideDirector

        return {"NextTurnGuide": NextTurnGuide, "NextTurnGuideDirector": NextTurnGuideDirector}[name]
    if name in ("DirectorThinkCompressor", "DIRECTOR_THINK_COMPRESS_RULES"):
        from .think_trace import DIRECTOR_THINK_COMPRESS_RULES, DirectorThinkCompressor

        return {
            "DirectorThinkCompressor": DirectorThinkCompressor,
            "DIRECTOR_THINK_COMPRESS_RULES": DIRECTOR_THINK_COMPRESS_RULES,
        }[name]
    if name == "PollScheduler":
        from .scheduler import PollScheduler

        return PollScheduler
    if name == "fallback_director_output":
        from .fallback import fallback_director_output

        return fallback_director_output
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
