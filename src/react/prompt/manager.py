from __future__ import annotations

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from config.react.prompt_config import PromptConfig
from react.memory.memory import Step
from react.memory.processor import MemoryResult
from react.prompt.template import get_template


class PromptManager:
    """
    Dynamic ReAct prompt manager backed by LangChain ChatPromptTemplate.

    Responsibilities:
    - Embed tool descriptions and memory context into the system message.
    - Maintain multi-turn conversation history (HumanMessage / AIMessage pairs)
      across successive stream() calls on the same TaoLoop instance.
    - Expose build_messages() → list[BaseMessage] for message-native LLM calls.
    """

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

    # ── public API ──────────────────────────────────────────────────────────

    def build_messages(self, question: str, result: MemoryResult) -> list[BaseMessage]:
        tpl = self._tpl

        system_parts = [self._base_system]
        if result.long_term:
            system_parts += [tpl.separator, tpl.long_term_header, result.long_term]
        if result.medium_term:
            system_parts += [tpl.separator, tpl.medium_term_header, result.medium_term]

        input_parts = [f"{tpl.question_prefix} {question}"]
        step_text = self._format_steps(result.short_term)
        if step_text:
            input_parts.append(step_text)
        input_parts.append(tpl.suffix)

        return self._template.format_messages(
            system="\n".join(system_parts),
            history=self._history,
            current_input="\n".join(input_parts),
        )

    def add_turn(self, question: str, answer: str) -> None:
        self._history.append(HumanMessage(content=f"{self._tpl.question_prefix} {question}"))
        self._history.append(AIMessage(content=answer))

    def clear_history(self) -> None:
        self._history.clear()

    @property
    def turn_count(self) -> int:
        return len(self._history) // 2

    # ── internal ────────────────────────────────────────────────────────────

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
