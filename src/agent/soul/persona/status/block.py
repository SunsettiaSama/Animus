from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from .emotional import EmotionalState


class StatusBlock(PromptBlock):
    """Agent 自身情绪状态块。"""

    def __init__(self, emotional: EmotionalState, max_chars: int = 600) -> None:
        self._emotional = emotional
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._emotional.is_empty():
            return None
        text = self._emotional.render()
        result = f"---\n## 当前情绪状态\n\n{text}"
        if self._max_chars > 0 and len(result) > self._max_chars:
            result = result[: self._max_chars]
        return result
