from __future__ import annotations

from dataclasses import dataclass

_MOOD_HEADER = "【瞬间情绪·你】"


@dataclass
class PersonaPresenceBlock:
    """presence 驱动的当下态：instant_mood 出站；state 为 narrative 合成源。"""

    state: str = ""
    instant_mood: str = ""

    def render(self) -> str:
        mood = self.instant_mood.strip()
        if not mood:
            return ""
        if mood.startswith(_MOOD_HEADER):
            return mood
        return f"{_MOOD_HEADER}\n{mood}"
