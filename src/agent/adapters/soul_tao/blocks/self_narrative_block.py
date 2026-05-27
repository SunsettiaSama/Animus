from __future__ import annotations

from agent.react.prompt.block import PromptBlock


class PresenceSelfNarrativeBlock(PromptBlock):
    """当下自我叙述块（由 SoulService 在线组装）。"""

    def __init__(self, narrative: str, max_chars: int = 900) -> None:
        self._narrative = narrative.strip()
        self._max_chars = max_chars

    def render(self) -> str | None:
        if not self._narrative:
            return None
        text = self._narrative
        if self._max_chars > 0 and len(text) > self._max_chars:
            text = text[: self._max_chars]
        return f"---\n## 当下自我叙述\n\n{text}"
