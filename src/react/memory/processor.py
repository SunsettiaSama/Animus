from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.react.memory.memory_config import MemoryConfig
from react.memory.long_term.init import make_memory
from react.memory.long_term.memory import LongTermMemory
from react.memory.medium_term.memory import MediumTermMemory
from react.memory.memory import Step
from react.memory.short_term.memory import ShortTermMemory

if TYPE_CHECKING:
    from llm_core.llm import LLM


@dataclass
class MemoryResult:
    short_term: list[Step] = field(default_factory=list)
    medium_term: str = ""
    long_term: str = ""


class MemoryProcessor:
    def __init__(self, cfg: MemoryConfig, llm: LLM | None = None):
        self._cfg = cfg

        self._short: ShortTermMemory | None = None
        if cfg.short_term.enabled:
            self._short = ShortTermMemory(cfg.short_term)

        self._medium: MediumTermMemory | None = None
        if cfg.medium_term.enabled:
            if llm is None:
                raise ValueError("LLM instance is required when medium_term memory is enabled")
            self._medium = MediumTermMemory(cfg.medium_term, llm)

        self._long: LongTermMemory | None = None
        if cfg.long_term.enabled:
            self._long = make_memory(cfg.long_term)

    def add(self, step: Step) -> None:
        evicted: list[Step] = []
        if self._short is not None:
            evicted = self._short.add(step)
        if self._medium is not None:
            self._medium.absorb(evicted)

    def recall(self, query: str = "") -> MemoryResult:
        return MemoryResult(
            short_term=self._short.steps() if self._short is not None else [],
            medium_term=self._medium.summary if self._medium is not None else "",
            long_term=self._long.recall(query) if self._long is not None else "",
        )

    def commit(self, question: str, answer: str) -> None:
        if self._medium is not None:
            self._medium.flush()

        if self._long is not None:
            parts = [f"Q: {question}"]
            if self._medium is not None and self._medium.has_summary:
                parts.append(f"Process: {self._medium.summary}")
            parts.append(f"A: {answer}")
            self._long.add("\n".join(parts), question=question)
            self._long.save()

    def clear(self) -> None:
        if self._short is not None:
            self._short.clear()
        if self._medium is not None:
            self._medium.clear()
