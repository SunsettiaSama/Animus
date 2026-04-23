from __future__ import annotations

from react.persona.chronicle.chronicle import PersonaChronicle
from react.prompt.block import PromptBlock


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


class ChronicleBlock(PromptBlock):
    """事件演化块 —— 渲染 PersonaChronicle 的最近 N 条叙事。"""

    def __init__(
        self,
        chronicle: PersonaChronicle,
        recent: int = 5,
        max_render_chars: int = 0,
        header: str = "【近期经历】",
        separator: str = "---",
    ) -> None:
        self._chronicle = chronicle
        self._recent = recent
        self._max_render_chars = max_render_chars
        self._header = header
        self._sep = separator

    def render(self) -> str | None:
        text = self._chronicle.render(recent=self._recent)
        if not text:
            return None
        rendered = f"{self._sep}\n{self._header}\n{text}"
        return _trunc(rendered, self._max_render_chars)
