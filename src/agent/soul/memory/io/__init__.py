"""Memory 对外 I/O 边界（与 Speak / Life 等子系统通信）。"""

from .hub import MemoryIO
from .life import (
    DialogueCloseInbound,
    ExperienceIngestInbound,
    LifeMemoryIO,
    LifeMemoryPort,
    LifeMemoryPortAdapter,
)
from .session import (
    DialogueCompressionBlock,
    DialogueTurnInbound,
    SessionIODeps,
    SessionSpeakIO,
    StaticPortraitInbound,
)

__all__ = [
    "DialogueCloseInbound",
    "DialogueCompressionBlock",
    "DialogueTurnInbound",
    "ExperienceIngestInbound",
    "LifeMemoryIO",
    "LifeMemoryPort",
    "LifeMemoryPortAdapter",
    "MemoryIO",
    "SessionIODeps",
    "SessionSpeakIO",
    "StaticPortraitInbound",
]
