from .chunk_types import DialogueContextChunk
from .render import (
    normalize_one_sentence,
    render_dialogue_compressed,
    render_dialogue_context_for_prompt,
    render_recent_turns_for_prompt,
    render_session_working_memory,
)

__all__ = [
    "DialogueContextChunk",
    "SpeakContextDistiller",
    "normalize_one_sentence",
    "render_dialogue_compressed",
    "render_dialogue_context_for_prompt",
    "render_recent_turns_for_prompt",
    "render_session_working_memory",
]


def __getattr__(name: str):
    if name == "SpeakContextDistiller":
        from .distiller import SpeakContextDistiller

        return SpeakContextDistiller
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
