from __future__ import annotations

from dataclasses import dataclass

from .memory import LifeExperienceMemoryIO
from .speak import LifeSpeakIO


@dataclass
class LifeIOHub:
    """Life 对外 I/O：Speak 入站 + Memory 出站。"""

    speak: LifeSpeakIO
    memory: LifeExperienceMemoryIO | None = None


__all__ = ["LifeIOHub", "LifeExperienceMemoryIO", "LifeSpeakIO"]
