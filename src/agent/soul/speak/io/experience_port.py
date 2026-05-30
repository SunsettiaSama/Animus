from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class SoulSpeakExperiencePort:
    """将 SoulService.experience 适配为 SpeakExperiencePort。"""

    def __init__(self, soul: SoulService) -> None:
        self._soul = soul

    @property
    def dialogue(self):
        return self._soul.experience.dialogue

    def close_dialogue(self, session_id: str) -> Any | None:
        return self._soul.experience.close_dialogue(session_id)
