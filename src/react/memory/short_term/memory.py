from __future__ import annotations

import json
from collections import deque
from typing import Callable

from config.react.memory.short_term_config import ShortTermMemoryConfig
from react.memory.memory import Step

_STEP_TEMPLATE = (
    "Thought: {thought}\n"
    "Action: {action}\n"
    "Action Input: {action_input}\n"
    "Observation: {observation}"
)


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
        tokenizer: Callable[[str], int] = _default_tokenizer,
    ):
        self._cfg = cfg
        self._tokenizer = tokenizer
        self._steps: deque[Step] = deque()
        self._token_count: int = 0

    def add(self, step: Step) -> list[Step]:
        tokens = self._tokenizer(_step_to_text(step))

        if tokens > self._cfg.max_tokens:
            raise ValueError(
                f"single step exceeds max_tokens ({tokens} > {self._cfg.max_tokens})"
            )

        self._steps.append(step)
        self._token_count += tokens

        return self._slide()

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

    def steps(self) -> list[Step]:
        return list(self._steps)

    def clear(self) -> None:
        self._steps.clear()
        self._token_count = 0

    @property
    def token_count(self) -> int:
        return self._token_count

    def __len__(self) -> int:
        return len(self._steps)
