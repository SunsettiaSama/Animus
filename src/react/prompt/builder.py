from __future__ import annotations

import json

from config.react.prompt_config import PromptConfig
from react.memory.memory import Step
from react.memory.processor import MemoryResult
from react.prompt.template import PromptTemplate, get_template


class PromptBuilder:
    def __init__(self, tool_descriptions: dict[str, str], cfg: PromptConfig | None = None):
        self._tool_descriptions = tool_descriptions
        self._tpl: PromptTemplate = get_template((cfg or PromptConfig()).lang)

    def build(self, question: str, result: MemoryResult) -> str:
        tpl = self._tpl
        sep = tpl.separator

        tool_list = "\n".join(
            f"- {name}: {desc}"
            for name, desc in self._tool_descriptions.items()
        )
        system = tpl.system.format(tool_list=tool_list)

        sections: list[str] = [system, sep]

        if result.long_term:
            sections.append(tpl.long_term_header)
            sections.append(result.long_term)

        if result.medium_term:
            sections.append(tpl.medium_term_header)
            sections.append(result.medium_term)

        if result.long_term or result.medium_term:
            sections.append(sep)

        sections.append(f"{tpl.question_prefix} {question}")

        history = self._format_steps(result.short_term)
        if history:
            sections.append(history)

        sections.append(tpl.suffix)

        return "\n".join(sections)

    def _format_steps(self, steps: list[Step]) -> str:
        return "\n".join(
            self._tpl.step_format.format(
                thought=s.thought,
                action=s.action,
                action_input=json.dumps(s.action_input, ensure_ascii=False),
                observation=s.observation,
            )
            for s in steps
        )
