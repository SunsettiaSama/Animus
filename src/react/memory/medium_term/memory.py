from __future__ import annotations

import json
from typing import TYPE_CHECKING

from config.react.memory.medium_term_config import MediumTermMemoryConfig
from react.memory.memory import Step

if TYPE_CHECKING:
    from llm_core.llm import LLM

_STEP_TEMPLATE = (
    "Thought: {thought}\n"
    "Action: {action}\n"
    "Action Input: {action_input}\n"
    "Observation: {observation}"
)

_SUMMARY_PROMPT = """\
You are a memory summarizer for a ReAct reasoning agent.
Your task: produce a concise updated summary that captures the key findings and \
progress made so far, within {max_tokens} words.

Previous Summary:
{prev_summary}

New Steps to Absorb:
{new_steps}

Write only the updated summary, no preamble."""


def _step_to_text(step: Step) -> str:
    return _STEP_TEMPLATE.format(
        thought=step.thought,
        action=step.action,
        action_input=json.dumps(step.action_input, ensure_ascii=False),
        observation=step.observation,
    )


class MediumTermMemory:
    def __init__(self, cfg: MediumTermMemoryConfig, llm: LLM):
        self._cfg = cfg
        self._llm = llm
        self._summary: str = ""
        self._pending: list[Step] = []

    def absorb(self, evicted_steps: list[Step]) -> None:
        if not evicted_steps:
            return

        self._pending.extend(evicted_steps)

        if len(self._pending) >= self._cfg.summary_trigger_steps:
            self._roll_summary()

    def flush(self) -> None:
        if self._pending:
            self._roll_summary()

    def _roll_summary(self) -> None:
        new_steps_text = "\n\n".join(_step_to_text(s) for s in self._pending)
        prev = self._summary if self._summary else "None"

        prompt = _SUMMARY_PROMPT.format(
            max_tokens=self._cfg.max_summary_tokens,
            prev_summary=prev,
            new_steps=new_steps_text,
        )

        self._summary = self._llm.generate(prompt)
        self._pending.clear()

    @property
    def summary(self) -> str:
        return self._summary

    @property
    def has_summary(self) -> bool:
        return bool(self._summary)

    def clear(self) -> None:
        self._summary = ""
        self._pending.clear()
