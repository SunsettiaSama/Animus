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

_DISTILL_PROMPT = """\
You are a knowledge distiller for a ReAct reasoning agent.
The following steps were evicted from short-term memory. Extract only what is \
genuinely useful for future reasoning, within {max_tokens} words.

Previous Distillate:
{prev_distillate}

Evicted Steps to Distill:
{evicted_steps}

Produce an updated distillate that captures:
1. Key facts discovered (tool results and observations that matter)
2. Successful reasoning paths (what worked and why)
3. Dead ends or failed attempts (to avoid repetition)

Output only the distillate, no preamble."""


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
        self._distillate: str = ""
        self._pending: list[Step] = []

    def absorb(self, evicted_steps: list[Step]) -> None:
        if not evicted_steps:
            return

        self._pending.extend(evicted_steps)

        if len(self._pending) >= self._cfg.distill_trigger_steps:
            self._distill()

    def flush(self) -> None:
        if self._pending:
            self._distill()

    def _distill(self) -> None:
        evicted_text = "\n\n".join(_step_to_text(s) for s in self._pending)
        prev = self._distillate if self._distillate else "None"

        prompt = _DISTILL_PROMPT.format(
            max_tokens=self._cfg.max_distillate_tokens,
            prev_distillate=prev,
            evicted_steps=evicted_text,
        )

        self._distillate = self._llm.generate(prompt)
        self._pending.clear()

    @property
    def distillate(self) -> str:
        return self._distillate

    @property
    def has_distillate(self) -> bool:
        return bool(self._distillate)

    def clear(self) -> None:
        self._distillate = ""
        self._pending.clear()
