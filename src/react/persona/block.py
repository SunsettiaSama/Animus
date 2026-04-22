from __future__ import annotations

from react.persona.chronicle import PersonaChronicle
from react.persona.profile import PersonaProfile
from react.prompt.block import PromptBlock


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


class ProfileBlock(PromptBlock):
    """人物画像块 —— 渲染 PersonaProfile 的静态描述。"""

    def __init__(self, profile: PersonaProfile, max_chars: int = 0) -> None:
        self._profile = profile
        self._max_chars = max_chars

    def render(self) -> str | None:
        return _trunc(self._profile.render(), self._max_chars)


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
        rendered = "\n".join([self._sep, self._header, text])
        return _trunc(rendered, self._max_render_chars)


class PersonaBlock(PromptBlock):
    """人格整合块 —— 将 ProfileBlock 与 ChronicleBlock 合并为单块。

    便利包装，适合不需要分开控制两者位置的场景。
    若需要独立调度，请直接使用 ProfileBlock 和 ChronicleBlock。
    """

    def __init__(
        self,
        profile: PersonaProfile,
        chronicle: PersonaChronicle,
        chronicle_recent: int = 5,
        max_profile_chars: int = 0,
        max_chronicle_render_chars: int = 0,
        separator: str = "---",
    ) -> None:
        self._profile_block = ProfileBlock(profile, max_chars=max_profile_chars)
        self._chronicle_block = ChronicleBlock(
            chronicle,
            recent=chronicle_recent,
            max_render_chars=max_chronicle_render_chars,
            separator=separator,
        )

    def render(self) -> str | None:
        parts = [self._profile_block.render()]
        chronicle_text = self._chronicle_block.render()
        if chronicle_text:
            parts.append(chronicle_text)
        return "\n".join(p for p in parts if p)
