from __future__ import annotations

from dataclasses import dataclass

from .life import LifeMemoryIO
from .session import SessionSpeakIO


@dataclass(frozen=True)
class MemoryIO:
    """Memory 对外 I/O 顶层：Speak 会话 + Life 体验。"""

    session: SessionSpeakIO
    life: LifeMemoryIO


__all__ = ["MemoryIO"]
