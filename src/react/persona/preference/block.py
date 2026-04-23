from __future__ import annotations

from react.persona.preference.recent import RecentPreference
from react.prompt.block import PromptBlock


class PreferenceBlock(PromptBlock):
    def __init__(self, recent: RecentPreference, max_chars: int = 300) -> None:
        self._recent = recent
        self._max_chars = max_chars

    def render(self) -> str | None:
        text = self._recent.render()
        if not text:
            return None
        result = f"【近期偏好（动态层）】\n{text}"
        if self._max_chars > 0 and len(result) > self._max_chars:
            result = result[: self._max_chars]
        return result
