from __future__ import annotations

from agent.react.prompt.block import PromptBlock

from .affect import AffectState


class PresenceAffectBlock(PromptBlock):
    """当下态附属情绪状态块（原 Persona StatusBlock）。"""

    def __init__(self, affect: AffectState, max_chars: int = 600) -> None:
        self._affect = affect
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._affect.is_empty():
            return None
        text = self._affect.render()
        result = f"---\n## 当下状态\n\n{text}"
        if self._max_chars > 0 and len(result) > self._max_chars:
            result = result[: self._max_chars]
        return result
