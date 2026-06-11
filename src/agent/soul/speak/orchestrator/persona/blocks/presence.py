from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaPresenceBlock:
    """presence 驱动的当下态：instant_mood 出站；state 为 narrative 合成源。"""

    state: str = ""
    instant_mood: str = ""

    def render(self) -> str:
        mood = self.instant_mood.strip()
        if not mood:
            return ""
        if mood.startswith("你"):
            return mood
        return f"你此刻{mood.rstrip('。')}。"
