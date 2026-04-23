from __future__ import annotations

import json
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
    from react.memory.milestone.memory import MilestoneMemory


@dataclass
class MemoryResult:
    short_term: list[Step] = field(default_factory=list)
    medium_term: str = ""
    long_term: str = ""
    milestone: str = ""


class MemoryProcessor:
    def __init__(
        self,
        cfg: MemoryConfig,
        llm: LLM | None = None,
        long_term: LongTermMemory | None = None,
        milestone: MilestoneMemory | None = None,
    ):
        self._cfg = cfg
        self._trace: list[Step] = []
        self._is_session_start: bool = True

        self._short: ShortTermMemory | None = None
        if cfg.short_term.enabled:
            self._short = ShortTermMemory(cfg.short_term)

        self._medium: MediumTermMemory | None = None
        if cfg.medium_term.enabled:
            if llm is None:
                raise ValueError("LLM instance is required when medium_term memory is enabled")
            self._medium = MediumTermMemory(cfg.medium_term, llm)

        self._long: LongTermMemory | None = long_term
        if self._long is None and cfg.long_term.enabled:
            self._long = make_memory(cfg.long_term)

        self._milestone: MilestoneMemory | None = milestone

    def add(self, step: Step) -> None:
        self._trace.append(step)

        evicted: list[Step] = []
        if self._short is not None:
            evicted = self._short.add(step)
        if self._medium is not None:
            self._medium.absorb(evicted)

    def recall(self, query: str = "", include_long_term: bool = True) -> MemoryResult:
        """Return current memory state.

        Args:
            query: Natural-language query used for long-term vector retrieval.
            include_long_term: When False the long-term recall is skipped and
                ``MemoryResult.long_term`` is returned as ``""``.  Pass
                ``False`` for ReAct steps after the first one so the
                expensive embedding search is only performed once per question.
        """
        short_steps = self._short.steps() if self._short is not None else []
        medium_text = self._medium.distillate if self._medium is not None else ""

        long_text = ""
        if include_long_term and self._long is not None:
            short_ctx = "\n".join(
                f"{s.thought} {s.observation}" for s in short_steps
            )
            long_text = self._long.smart_recall(
                query=query,
                is_session_start=self._is_session_start,
                short_term_context=short_ctx,
                medium_term_context=medium_text,
            )
            self._is_session_start = False

        milestone_text = ""
        if self._milestone is not None and query:
            milestone_text = self._milestone.retrieve(query)

        return MemoryResult(
            short_term=short_steps,
            medium_term=medium_text,
            long_term=long_text,
            milestone=milestone_text,
        )

    def commit(self, question: str, answer: str) -> None:
        if self._medium is not None:
            self._medium.flush()

        if self._long is not None:
            parts = [f"Q: {question}"]

            if self._trace:
                step_blocks = []
                for s in self._trace:
                    step_blocks.append(
                        f"Thought: {s.thought}\n"
                        f"Action: {s.action}\n"
                        f"Action Input: {json.dumps(s.action_input, ensure_ascii=False)}\n"
                        f"Observation: {s.observation}"
                    )
                parts.append("Steps:\n" + "\n---\n".join(step_blocks))

            if self._medium is not None and self._medium.has_distillate:
                parts.append(f"Distillate: {self._medium.distillate}")

            parts.append(f"A: {answer}")
            self._long.add("\n".join(parts), question=question)
            self._long.save()

        if self._milestone is not None:
            added, evicted = self._milestone.try_add(question, answer, self._trace)
            if added:
                self._milestone.save()
            # 溢出的里程碑条目迁移到 L3，确保不丢失
            if evicted and self._long is not None:
                for e in evicted:
                    text = f"[迁移自里程碑] {e.summary}\n{e.detail}"
                    self._long.add(text, source="milestone", importance=e.importance)
                self._long.save()

    def clear(self) -> None:
        self._trace.clear()
        self._is_session_start = True
        if self._short is not None:
            self._short.clear()
        if self._medium is not None:
            self._medium.clear()

    @property
    def trace(self) -> list[Step]:
        return list(self._trace)

    @property
    def medium_distillate(self) -> str:
        """Current medium-term distillate text (empty string if disabled)."""
        return self._medium.distillate if self._medium is not None else ""
