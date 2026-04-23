from __future__ import annotations

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


_LT_DISTILL_PROMPT = """\
You are a knowledge distiller for a long-term memory system.
Given the conversation below, extract only the most valuable and reusable \
knowledge — key facts, conclusions, and insights — within {max_tokens} words. \
Omit procedural steps, tool calls, and ephemeral details.

Question: {question}

Answer: {answer}

Output only the distilled knowledge entry, no preamble."""


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
        medium_term: RecentHistoryMemory | None = None,
    ):
        self._cfg = cfg
        self._llm = llm
        self._trace: list[Step] = []
        self._is_session_start: bool = True

        self._short: ShortTermMemory | None = None
        if cfg.short_term.enabled:
            self._short = ShortTermMemory(cfg.short_term, llm=llm)

        # Accept an externally managed instance (shared across turns in TaoLoop)
        # or fall back to creating a new one if none is provided.
        self._medium: RecentHistoryMemory | None = medium_term
        if self._medium is None and cfg.medium_term.enabled:
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
            lt_text = self._build_lt_entry(question, answer)
            self._long.add(lt_text, question=question)
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

    def _build_lt_entry(self, question: str, answer: str) -> str:
        """Build the text to store in long-term memory for this turn.

        - distill_enabled=False (default): store only the answer; the question
          is kept as metadata so vector search can still match on it.
        - distill_enabled=True + llm available: ask the LLM to extract a
          concise knowledge summary from Q+A; fall back to answer-only on error.
        """
        cfg = self._cfg.long_term
        if cfg.distill_enabled and self._llm is not None:
            prompt = _LT_DISTILL_PROMPT.format(
                max_tokens=cfg.max_distill_tokens,
                question=question,
                answer=answer,
            )
            distilled = self._llm.generate(prompt).strip()
            if distilled:
                return distilled
        # Default / fallback: answer only
        return answer

    def clear(self) -> None:
        self._trace.clear()
        self._is_session_start = True
        if self._short is not None:
            self._short.clear()

    @property
    def trace(self) -> list[Step]:
        return list(self._trace)
