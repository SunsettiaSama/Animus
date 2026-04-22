from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from config.react.prompt_config import PromptConfig
from react.memory.processor import MemoryResult
from react.prompt.block import MemoryBlock, PromptBlock, QuestionBlock, StepsBlock, SuffixBlock, SystemBlock
from react.prompt.template import get_template

if TYPE_CHECKING:
    from react.memory.memory import Step


@dataclass
class StaticPromptParts:
    """Pre-assembled prompt parts that do not depend on the next user question.

    Built in the background after each turn's commit completes.  When the user
    sends the next message only the long-term recall slot needs to be filled in
    before the full message list can be constructed.

    Fields:
        system_without_lt: Rendered system string containing the base system
            prompt, persona blocks, and medium-term distillate — but **not**
            the long-term recall block (that slot is filled per-question).
        history: Snapshot of the conversation history taken right after the
            previous turn's ``add_turn()`` call.
    """
    system_without_lt: str
    history: list[BaseMessage] = field(default_factory=list)


class PromptManager:
    def __init__(
        self,
        tool_descriptions: dict[str, str],
        cfg: PromptConfig | None = None,
    ) -> None:
        self._tpl = get_template((cfg or PromptConfig()).lang)

        tool_list = "\n".join(
            f"- {name}: {desc}" for name, desc in tool_descriptions.items()
        )
        self._base_system: str = self._tpl.system.format(tool_list=tool_list)

        self._template = ChatPromptTemplate.from_messages([
            ("system", "{system}"),
            MessagesPlaceholder(variable_name="history"),
            ("human", "{current_input}"),
        ])

        self._history: list[BaseMessage] = []

    def build_messages(
        self,
        question: str,
        result: MemoryResult,
        extra_system_blocks: list[PromptBlock] | None = None,
    ) -> list[BaseMessage]:
        tpl = self._tpl

        system_blocks: list[PromptBlock] = [SystemBlock(self._base_system)]
        if extra_system_blocks:
            system_blocks.extend(extra_system_blocks)
        system_blocks += [
            MemoryBlock(tpl.long_term_header, tpl.separator, result.long_term),
            MemoryBlock(tpl.medium_term_header, tpl.separator, result.medium_term),
        ]
        human_blocks: list[PromptBlock] = [
            QuestionBlock(tpl.question_prefix, question),
            StepsBlock(tpl.step_format, result.short_term),
            SuffixBlock(tpl.suffix),
        ]

        system = "\n".join(b for block in system_blocks if (b := block.render()) is not None)
        human = "\n".join(b for block in human_blocks if (b := block.render()) is not None)

        return self._template.format_messages(
            system=system,
            history=self._history,
            current_input=human,
        )

    def build_static(
        self,
        medium_term: str = "",
        extra_system_blocks: list[PromptBlock] | None = None,
    ) -> StaticPromptParts:
        """Build the static parts of the next prompt (background pre-assembly).

        Includes everything *except* the long-term recall block, because that
        block requires the user's next question as the retrieval query.

        Call this at the end of :meth:`post_process` so the cache is ready
        before the user sends the next message.
        """
        tpl = self._tpl
        system_blocks: list[PromptBlock] = [SystemBlock(self._base_system)]
        if extra_system_blocks:
            system_blocks.extend(extra_system_blocks)
        system_blocks.append(
            MemoryBlock(tpl.medium_term_header, tpl.separator, medium_term)
        )
        system_without_lt = "\n".join(
            b for block in system_blocks if (b := block.render()) is not None
        )
        return StaticPromptParts(
            system_without_lt=system_without_lt,
            history=list(self._history),
        )

    def build_messages_from_static(
        self,
        static: StaticPromptParts,
        question: str,
        long_term: str = "",
        short_term: list[Step] | None = None,
    ) -> list[BaseMessage]:
        """Complete prompt assembly using a pre-built :class:`StaticPromptParts`.

        Only the long-term recall text and per-step dynamic data (question,
        scratchpad steps, suffix) are injected here, keeping this path fast.
        """
        tpl = self._tpl

        # Inject long-term recall into the pre-built system string
        lt_block = MemoryBlock(tpl.long_term_header, tpl.separator, long_term)
        lt_rendered = lt_block.render()
        system = static.system_without_lt
        if lt_rendered:
            system = system + "\n" + lt_rendered

        human_blocks: list[PromptBlock] = [
            QuestionBlock(tpl.question_prefix, question),
            StepsBlock(tpl.step_format, short_term or []),
            SuffixBlock(tpl.suffix),
        ]
        human = "\n".join(
            b for block in human_blocks if (b := block.render()) is not None
        )
        return self._template.format_messages(
            system=system,
            history=static.history,
            current_input=human,
        )

    def add_turn(self, question: str, answer: str) -> None:
        self._history.append(HumanMessage(content=f"{self._tpl.question_prefix} {question}"))
        self._history.append(AIMessage(content=answer))

    def recent_turns(self, k: int) -> list[tuple[str, str]]:
        """Return last k (question, answer) pairs from history."""
        items = self._history[-k * 2:] if k > 0 else []
        prefix = f"{self._tpl.question_prefix} "
        pairs = []
        for i in range(0, len(items) - 1, 2):
            q = items[i].content
            if q.startswith(prefix):
                q = q[len(prefix):]
            pairs.append((q, items[i + 1].content))
        return pairs

    def clear_history(self) -> None:
        self._history.clear()

    @property
    def turn_count(self) -> int:
        return len(self._history) // 2
