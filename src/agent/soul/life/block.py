from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from .profile import LifeProfile


class LifeProfileBlock(PromptBlock):
    def __init__(self, profile: LifeProfile, max_chars: int = 500) -> None:
        self._profile = profile
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._profile.is_empty():
            return None
        text = self._profile.render()
        if self._max_chars > 0 and len(text) > self._max_chars:
            text = text[-self._max_chars:]
        return f"---\n## 近期生活状态\n\n{text}"
