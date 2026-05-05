from __future__ import annotations

import json
from collections import deque
from typing import TYPE_CHECKING, Callable

from config.agent.memory.short_term_config import ShortTermMemoryConfig
from ...memory.memory import Step

if TYPE_CHECKING:
    from llm_core.llm import BaseLLM

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


def _default_tokenizer(text: str) -> int:
    return len(text.split())


class ShortTermMemory:
    def __init__(
        self,
        cfg: ShortTermMemoryConfig,
        llm: BaseLLM | None = None,
        tokenizer: Callable[[str], int] = _default_tokenizer,
    ):
        self._cfg = cfg
        self._tokenizer = tokenizer
        self._steps: deque[Step] = deque()
        self._token_count: int = 0

        # 蒸馏状态（仅在 llm 可用且 distill_enabled 时激活）
        self._llm: BaseLLM | None = llm if cfg.distill_enabled else None
        self._pending: list[Step] = []
        self._distillate: str = ""

    def add(self, step: Step) -> list[Step]:
        tokens = self._tokenizer(_step_to_text(step))

        if tokens > self._cfg.max_tokens:
            raise ValueError(
                f"single step exceeds max_tokens ({tokens} > {self._cfg.max_tokens})"
            )

        self._steps.append(step)
        self._token_count += tokens

        evicted = self._slide()
        if evicted and self._llm is not None:
            self._pending.extend(evicted)
            if len(self._pending) >= self._cfg.distill_trigger_steps:
                self._distill()

        return evicted

    def flush(self) -> None:
        """session 结束时强制蒸馏剩余 pending 步骤。"""
        if self._llm is not None and self._pending:
            self._distill()

    def _slide(self) -> list[Step]:
        evicted: list[Step] = []
        while self._steps and (
            len(self._steps) > self._cfg.max_turns
            or self._token_count > self._cfg.max_tokens
        ):
            step = self._steps.popleft()
            self._token_count -= self._tokenizer(_step_to_text(step))
            evicted.append(step)
        return evicted

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

    def steps(self) -> list[Step]:
        return list(self._steps)

    def clear(self) -> None:
        self._steps.clear()
        self._token_count = 0
        self._pending.clear()
        self._distillate = ""

    @property
    def distillate(self) -> str:
        return self._distillate

    @property
    def token_count(self) -> int:
        return self._token_count

    def __len__(self) -> int:
        return len(self._steps)
