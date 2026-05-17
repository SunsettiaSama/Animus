from __future__ import annotations

from typing import Protocol

from agent.react.prompt.block import PromptBlock


class _SupportsSkillsPrompt(Protocol):
    def render(self, top_k: int) -> str | None:
        ...


def _trunc(text: str, limit: int) -> str:
    return text[:limit] if limit > 0 and len(text) > limit else text


class ProfileBlock(PromptBlock):
    """人物画像块。

    接受任何实现了 render() -> str 的对象（PersonaProfile 或 BuiltProfile）。
    """

    def __init__(self, profile: object, max_chars: int = 0) -> None:
        self._profile = profile
        self._max_chars = max_chars

    def render(self) -> str | None:
        return _trunc(self._profile.render(), self._max_chars)


class SkillsBlock(PromptBlock):
    """行为技能块 —— 渲染优先级最高的 top_k 条技能。"""

    def __init__(
        self,
        skills: _SupportsSkillsPrompt,
        top_k: int = 5,
        max_chars: int = 0,
        separator: str = "---",
    ) -> None:
        self._skills = skills
        self._top_k = top_k
        self._max_chars = max_chars
        self._sep = separator

    def render(self) -> str | None:
        text = self._skills.render(top_k=self._top_k)
        if not text:
            return None
        return _trunc(f"{self._sep}\n{text}", self._max_chars)


class ReflectionBlock(PromptBlock):
    """自省块 —— 注入 Agent 第一人称自我感知表述（IROTE 机制）。"""

    def __init__(
        self,
        reflection: str,
        max_chars: int = 0,
        header: str = "【自我感知】",
        separator: str = "---",
    ) -> None:
        self._reflection = reflection
        self._max_chars = max_chars
        self._header = header
        self._sep = separator

    def render(self) -> str | None:
        text = self._reflection.strip()
        if not text:
            return None
        return _trunc(f"{self._sep}\n{self._header}\n{text}", self._max_chars)
