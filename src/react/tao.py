from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Generator, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.memory.long_term.init import make_memory
from react.memory.long_term.memory import LongTermMemory
from react.memory.memory import Step
from react.memory.processor import MemoryProcessor, MemoryResult
from react.parser import parse_llm_output
from react.persona import PersonaManager
from react.prompt.block import PromptBlock
from react.prompt.manager import PromptManager, StaticPromptParts
from react.trace import TraceStore


# ── Events ───────────────────────────────────────────────────────────────────

@dataclass
class StepStartEvent:
    index: int


@dataclass
class ChunkEvent:
    index: int
    chunk: str


@dataclass
class StepEvent:
    index: int
    thought: str
    action: str
    action_input: dict
    observation: str


@dataclass
class FinishEvent:
    answer: str


@dataclass
class PromptPreviewEvent:
    messages: list[dict] = field(default_factory=list)


TaoEvent = Union[StepStartEvent, ChunkEvent, StepEvent, FinishEvent, PromptPreviewEvent]


# ── Pending finish state (stored between stream() and post_process()) ─────────

@dataclass
class _PendingFinish:
    question: str
    answer: str
    processor: MemoryProcessor
    persona_blocks: list[PromptBlock] | None


# ── TaoLoop ───────────────────────────────────────────────────────────────────

class TaoLoop:
    def __init__(
        self,
        llm: LLM,
        executor: ActionExecutor,
        tool_descriptions: dict[str, str],
        cfg: TaoConfig,
    ):
        self._llm = llm
        self._executor = executor
        self._cfg = cfg
        self._manager = PromptManager(tool_descriptions, cfg.prompt)
        self._trace_store: TraceStore | None = (
            TraceStore(cfg.trace) if cfg.trace.enabled else None
        )
        self._persona: PersonaManager | None = (
            PersonaManager(cfg.persona) if cfg.persona.enabled else None
        )
        self._long_term: LongTermMemory | None = (
            make_memory(cfg.memory.long_term) if cfg.memory.long_term.enabled else None
        )

        # Pre-assembled static prompt parts for the next turn.
        # None on first turn; rebuilt in post_process() after each commit.
        self._static_cache: StaticPromptParts | None = None

        # Commit payload set inside stream() and consumed by post_process().
        self._pending_finish: _PendingFinish | None = None

    @staticmethod
    def _trunc(text: str, limit: int) -> str:
        return text[:limit] if limit > 0 and len(text) > limit else text

    # ── Core streaming loop ───────────────────────────────────────────────────

    def stream(self, question: str) -> Generator[TaoEvent, None, None]:
        question = self._trunc(question, self._cfg.prompt.max_question_chars)
        processor = MemoryProcessor(self._cfg.memory, self._llm, long_term=self._long_term)

        # Long-term recall result cached after step 0 (expensive vector search
        # is only run once per question, reused for subsequent ReAct steps).
        _cached_lt: str = ""

        for i in range(self._cfg.max_steps):
            # ── Memory recall ────────────────────────────────────────────────
            # Long-term search only at step 0; subsequent steps reuse the result.
            result = processor.recall(question, include_long_term=(i == 0))
            if i == 0:
                _cached_lt = result.long_term

            # ── Persona blocks ───────────────────────────────────────────────
            persona_blocks: list[PromptBlock] | None = (
                [self._persona.profile_block(), self._persona.chronicle_block()]
                if self._persona is not None else None
            )

            # ── Message assembly ─────────────────────────────────────────────
            # Use the pre-built static cache when available: avoids re-rendering
            # system/persona/medium-term on every turn.  Only the long-term slot
            # and the per-step dynamic parts (question, scratchpad, suffix) are
            # injected here.
            if self._static_cache is not None:
                messages = self._manager.build_messages_from_static(
                    self._static_cache,
                    question=question,
                    long_term=_cached_lt,
                    short_term=result.short_term,
                )
            else:
                # First turn or cache invalidated — full build path.
                messages = self._manager.build_messages(
                    question,
                    MemoryResult(
                        short_term=result.short_term,
                        medium_term=result.medium_term,
                        long_term=_cached_lt,
                    ),
                    extra_system_blocks=persona_blocks,
                )

            # ── Prompt preview (step 0 only) ─────────────────────────────────
            if i == 0:
                preview: list[dict] = []
                for msg in messages:
                    if isinstance(msg, SystemMessage):
                        preview.append({"role": "system", "content": msg.content})
                    elif isinstance(msg, HumanMessage):
                        preview.append({"role": "user", "content": msg.content})
                    elif isinstance(msg, AIMessage):
                        preview.append({"role": "assistant", "content": msg.content})
                yield PromptPreviewEvent(messages=preview)

            yield StepStartEvent(index=i)

            # ── LLM generation ───────────────────────────────────────────────
            raw_output = ""
            for chunk in self._llm.stream_generate_messages(messages):
                raw_output += chunk
                yield ChunkEvent(index=i, chunk=chunk)

            thought, action, action_input = parse_llm_output(raw_output)

            if action.lower() == self._cfg.finish_action:
                answer = action_input.get("answer", raw_output)

                # Store commit payload — caller invokes post_process() in
                # background AFTER FinishEvent is delivered to the client.
                self._pending_finish = _PendingFinish(
                    question=question,
                    answer=answer,
                    processor=processor,
                    persona_blocks=persona_blocks,
                )
                yield FinishEvent(answer=answer)
                return

            # ── Tool execution ───────────────────────────────────────────────
            observation = self._executor.run(
                json.dumps({"action": action, "args": action_input}, ensure_ascii=False)
            )
            observation = self._trunc(observation, self._cfg.prompt.max_observation_chars)

            step = Step(
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )
            processor.add(step)

            yield StepEvent(
                index=i,
                thought=thought,
                action=action,
                action_input=action_input,
                observation=observation,
            )

        raise RuntimeError(f"TaoLoop exceeded max_steps={self._cfg.max_steps} without finishing")

    # ── Post-processing (runs in background after FinishEvent is delivered) ───

    def post_process(self) -> None:
        """Commit memory, evolve persona, update history, and rebuild the static
        prompt cache for the next turn.

        This method is designed to be called from a background thread *after*
        :class:`FinishEvent` has already been sent to the client, so the user
        does not wait for embedding / disk-write / LLM-distillation operations.
        """
        pf = self._pending_finish
        if pf is None:
            return
        self._pending_finish = None

        pf.processor.commit(pf.question, pf.answer)

        if self._trace_store is not None:
            self._trace_store.write(pf.question, pf.answer, pf.processor.trace)

        if self._persona is not None:
            self._persona.evolve(pf.question, pf.answer, pf.processor.trace)

        self._manager.add_turn(pf.question, pf.answer)
        self._maybe_consolidate()

        # Pre-build the static parts for the next turn while the user is
        # reading the current answer (or typing the next question).
        self._static_cache = self._manager.build_static(
            medium_term=pf.processor.medium_distillate,
            extra_system_blocks=pf.persona_blocks,
        )

    # ── Misc ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        self._manager.clear_history()
        self._static_cache = None
        self._pending_finish = None

    def run(self, question: str) -> str:
        for event in self.stream(question):
            if isinstance(event, FinishEvent):
                self.post_process()
                return event.answer
        raise RuntimeError(f"TaoLoop exceeded max_steps={self._cfg.max_steps} without finishing")

    # ── Long-term memory consolidation ───────────────────────────────────────

    def _maybe_consolidate(self) -> None:
        k = self._cfg.memory.long_term.consolidation_k
        if k <= 0 or self._long_term is None:
            return
        n = self._manager.turn_count
        if n > 0 and n % k == 0:
            self._consolidate(k, n)

    def _consolidate(self, k: int, turn: int) -> None:
        turns = self._manager.recent_turns(k)
        if not turns:
            return

        parts = [f"[会话窗口整合 @ 第 {turn} 轮]"]
        for idx, (q, a) in enumerate(turns, 1):
            parts.append(f"\n第 {idx} 轮：\nQ: {q}\nA: {a}")

        self._long_term.add(
            "\n".join(parts),
            source="consolidation",
            turn=turn,
        )
        self._long_term.save()
