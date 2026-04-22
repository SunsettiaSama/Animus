from __future__ import annotations

from config.react.prompt_config import PromptConfig
from react.memory.processor import MemoryResult
from react.prompt.block import MemoryBlock, QuestionBlock, StepsBlock, SuffixBlock, SystemBlock
from react.prompt.template import get_template


class PromptBuilder:
    def __init__(self, tool_descriptions: dict[str, str], cfg: PromptConfig | None = None):
        self._tpl = get_template((cfg or PromptConfig()).lang)

        tool_list = "\n".join(
            f"- {name}: {desc}" for name, desc in tool_descriptions.items()
        )
        self._base_system: str = self._tpl.system.format(tool_list=tool_list)

    def build(self, question: str, result: MemoryResult) -> str:
        tpl = self._tpl

        blocks = [
            SystemBlock(self._base_system),
            MemoryBlock(tpl.long_term_header, tpl.separator, result.long_term),
            MemoryBlock(tpl.medium_term_header, tpl.separator, result.medium_term),
            QuestionBlock(tpl.question_prefix, question),
            StepsBlock(tpl.step_format, result.short_term),
            SuffixBlock(tpl.suffix),
        ]

        return "\n".join(b for block in blocks if (b := block.render()) is not None)
