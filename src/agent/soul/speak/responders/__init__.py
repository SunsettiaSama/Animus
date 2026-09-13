from .types import (
    DEFAULT_SPEAK_RESPONDER,
    SpeakResponderName,
    SpeakResponderRunner,
    normalize_speak_responder,
)

__all__ = [
    "DEFAULT_SPEAK_RESPONDER",
    "DirectPipelineRunner",
    "RhythmPipelineRunner",
    "SpeakResponderName",
    "SpeakResponderRouter",
    "SpeakResponderRunner",
    "normalize_speak_responder",
]


def __getattr__(name: str):
    if name == "RhythmPipelineRunner":
        from .rhythm import RhythmPipelineRunner

        return RhythmPipelineRunner
    if name == "DirectPipelineRunner":
        from .direct import DirectPipelineRunner

        return DirectPipelineRunner
    if name == "SpeakResponderRouter":
        from .router import SpeakResponderRouter

        return SpeakResponderRouter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
