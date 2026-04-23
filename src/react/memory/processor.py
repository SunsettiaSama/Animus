from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.react.memory.memory_config import MemoryConfig
from react.memory.long_term.init import make_memory
from react.memory.long_term.memory import LongTermMemory
from react.memory.medium_term.memory import RecentHistoryMemory
from react.memory.memory import Step
from react.memory.short_term.memory import ShortTermMemory

if TYPE_CHECKING:
    from llm_core.llm import LLM
    from react.memory.milestone.memory import MilestoneMemory


@dataclass
class MemoryResult:
    short_term: list[Step] = field(default_factory=list)
    short_term_distillate: str = ""
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
            self._short = ShortTermMemory(cfg.short_term, llm=llm)

        self._medium: RecentHistoryMemory | None = None
        if cfg.medium_term.enabled:
            self._medium = RecentHistoryMemory(cfg.medium_term, llm=llm)

        self._long: LongTermMemory | None = long_term
        if self._long is None and cfg.long_term.enabled:
            self._long = make_memory(cfg.long_term)

        self._milestone: MilestoneMemory | None = milestone

    def add(self, step: Step) -> None:
        self._trace.append(step)
        if self._short is not None:
            self._short.add(step)

    def recall(self, query: str = "", include_long_term: bool = True) -> MemoryResult:
        short_steps = self._short.steps() if self._short is not None else []
        short_distillate = self._short.distillate if self._short is not None else ""
        medium_text = self._medium.render() if self._medium is not None else ""

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
            short_term_distillate=short_distillate,
            medium_term=medium_text,
            long_term=long_text,
            milestone=milestone_text,
        )

    def commit(self, question: str, answer: str) -> None:
        """轮结束后落盘。在 post_process() 后台线程中调用，用户无感知。"""
        if self._short is not None:
            self._short.flush()

        if self._medium is not None:
            self._medium.append(question, answer)

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
            parts.append(f"A: {answer}")
            self._long.add("\n".join(parts), question=question)
            self._long.save()

        if self._milestone is not None:
            added, evicted = self._milestone.try_add(question, answer, self._trace)
            if added:
                self._milestone.save()
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

    @property
    def trace(self) -> list[Step]:
        return list(self._trace)
