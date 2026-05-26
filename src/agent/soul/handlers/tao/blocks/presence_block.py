from __future__ import annotations

from agent.react.prompt.block import PromptBlock
from agent.soul.presence.state import PresenceState


class PresenceBlock(PromptBlock):
    """当下态四维度自叙块。"""

    def __init__(self, state: PresenceState, max_chars: int = 900) -> None:
        self._state = state
        self._max_chars = max_chars

    def render(self) -> str | None:
        if self._state.is_empty():
            return None
        text = self._state.render()
        result = f"---\n## 当下状态\n\n{text}"
        if self._max_chars > 0 and len(result) > self._max_chars:
            result = result[: self._max_chars]
        return result


PresenceAffectBlock = PresenceBlock
