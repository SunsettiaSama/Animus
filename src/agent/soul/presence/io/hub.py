from __future__ import annotations

from .speak import PresenceSpeakIO

__all__ = ["PresenceIOHub"]


class PresenceIOHub:
    """Presence 对外 IO 总线。"""

    def __init__(self, *, speak: PresenceSpeakIO) -> None:
        self.speak = speak
