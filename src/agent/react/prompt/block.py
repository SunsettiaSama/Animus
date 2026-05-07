from __future__ import annotations

import json
from abc import ABC, abstractmethod

from langchain_core.prompts import PromptTemplate

from ..memory.memory import Step


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


def _render_step(step: Step, legacy_fmt: PromptTemplate) -> str:
    """Render a single Step to the prompt string.

    New-format steps (step.calls is not None) use XML tags:
        <T>...</T>
        <A>[{"action": "...", "args": {...}}, ...]</A>
        <O>...</O>          ← only when output is non-empty
        Observation[s]: ...

    Legacy steps (step.calls is None) continue to use the old PromptTemplate
    format to avoid corrupting historical context with missing fields.
    """
    if step.calls:
        calls_json = json.dumps(step.calls, ensure_ascii=False)
        thought_tag = f"<T>{step.thought}</T>" if step.thought else "<T></T>"
        action_tag  = f"<A>{calls_json}</A>"
        if len(step.calls) > 1:
            obs_section = f"Observations:\n{step.observation}"
        else:
            obs_section = f"Observation: {step.observation}"
        parts = [thought_tag, action_tag]
        if step.output:
            parts.append(f"<O>{step.output}</O>")
        parts.append(obs_section)
        return "\n".join(parts)

    # Legacy single-call format (step.calls is None — old conversations or old-format parse)
    return legacy_fmt.format(
        thought=step.thought,
        action=step.action,
        action_input=json.dumps(step.action_input, ensure_ascii=False),
        observation=step.observation,
    )


class StepsBlock(PromptBlock):
    def __init__(self, step_format: PromptTemplate, steps: list[Step]) -> None:
        self._step_format = step_format
        self._steps = steps

    def render(self) -> str | None:
        if not self._steps:
            return None
        return "\n".join(_render_step(s, self._step_format) for s in self._steps)


class SuffixBlock(PromptBlock):
    def __init__(self, text: str) -> None:
        self._text = text

    def render(self) -> str | None:
        return self._text
