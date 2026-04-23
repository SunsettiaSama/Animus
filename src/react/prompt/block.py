from __future__ import annotations

import json
from abc import ABC, abstractmethod

from langchain_core.prompts import PromptTemplate

from react.memory.memory import Step


class PromptBlock(ABC):
    @abstractmethod
    def render(self) -> str | None:
        """Return rendered text, or None to exclude this block from the prompt."""


class SystemBlock(PromptBlock):
    def __init__(self, text: str) -> None:
        self._text = text

    def render(self) -> str | None:
        return self._text


class MemoryBlock(PromptBlock):
    """Renders a labeled memory-tier block.

    Output format (content omitted when empty → block is skipped):

        ---
        ## <title>
        <desc>

        <content>
    """
    def __init__(self, title: str, desc: str, separator: str, content: str) -> None:
        self._title     = title
        self._desc      = desc
        self._separator = separator
        self._content   = content

    def render(self) -> str | None:
        if not self._content:
            return None
        parts = [self._separator, self._title]
        if self._desc:
            parts.append(self._desc)
        parts.append("")          # blank line before content
        parts.append(self._content)
        return "\n".join(parts)


class QuestionBlock(PromptBlock):
    def __init__(self, prefix: str, question: str) -> None:
        self._prefix = prefix
        self._question = question

    def render(self) -> str | None:
        return f"{self._prefix} {self._question}"


class StepsBlock(PromptBlock):
    def __init__(self, step_format: PromptTemplate, steps: list[Step]) -> None:
        self._step_format = step_format
        self._steps = steps

    def render(self) -> str | None:
        if not self._steps:
            return None
        return "\n".join(
            self._step_format.format(
                thought=s.thought,
                action=s.action,
                action_input=json.dumps(s.action_input, ensure_ascii=False),
                observation=s.observation,
            )
            for s in self._steps
        )


class SuffixBlock(PromptBlock):
    def __init__(self, text: str) -> None:
        self._text = text

    def render(self) -> str | None:
        return self._text
