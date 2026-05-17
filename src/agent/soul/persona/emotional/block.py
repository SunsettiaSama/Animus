from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from .state import EmotionalState


class EmotionalStateBlock(PromptBlock):
    def __init__(self, state: EmotionalState, max_chars: int = 400) -> None:
        self._state = state
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._state.is_empty():
            return None
        text = self._state.render()
        if self._max_chars > 0 and len(text) > self._max_chars:
            text = text[-self._max_chars:]
        return f"---\n## 近期情绪状态\n\n{text}"
