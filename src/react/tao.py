from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Generator, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config.react.tao_config import TaoConfig
from llm_core.handle import LLMHandle
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.action.tools.impl.memory_recall import MemoryRecallAction
from react.action.tools.impl.knowledge_hybrid_search import KnowledgeHybridSearchAction
from react.action.tools.impl.knowledge_save import KnowledgeSaveAction
from react.action.tools.impl.knowledge_list import KnowledgeListAction
from react.action.skill.domain_learning import DomainLearningSkill
from react.action.tools.impl.web_fetch import WebFetchAction
from react.action.tools.impl.web_search import WebSearchAction
from react.memory.long_term.init import make_memory
from react.memory.long_term.memory import LongTermMemory
from react.memory.medium_term.memory import RecentHistoryMemory
from react.memory.memory import Step
from react.memory.milestone.init import make_milestone
from react.memory.milestone.memory import MilestoneMemory
from react.memory.processor import MemoryProcessor, MemoryResult
from react.prompt.block import MemoryBlock, PromptBlock
from react.prompt.parser import ParseQuality, diagnose, parse_llm_output
from react.prompt.repair import repair
from react.persona import PersonaManager
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


@dataclass
class RetryEvent:
    index: int
    reason: str


TaoEvent = Union[StepStartEvent, ChunkEvent, StepEvent, FinishEvent, PromptPreviewEvent, RetryEvent]


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
        tool_category_summary: str = "",
    ):
        self._llm = LLMHandle(llm)   # shared handle — update_llm() swaps the inner LLM
        self._executor = executor
        self._cfg = cfg
        self._trace_store: TraceStore | None = (
            TraceStore(cfg.trace) if cfg.trace.enabled else None
        )
        self._persona: PersonaManager | None = (
            PersonaManager(cfg.persona, llm=self._llm) if cfg.persona.enabled else None
        )

        # Build memory stores before PromptManager so the recall tool can be
        # injected into the executor and its description added to the prompt.
        self._long_term: LongTermMemory | None = (
            make_memory(cfg.memory.long_term) if cfg.memory.long_term.enabled else None
        )
        self._milestone: MilestoneMemory | None = (
            make_milestone(cfg.memory.milestone, llm=self._llm)
            if cfg.memory.milestone.enabled
            else None
        )
        self._medium_term: RecentHistoryMemory | None = (
            RecentHistoryMemory(cfg.memory.medium_term, llm=self._llm)
            if cfg.memory.medium_term.enabled
            else None
        )

        # Inject the recall tool when at least one memory backend is active.
        # We copy tool_descriptions to avoid mutating the caller's dict.
        effective_descriptions = dict(tool_descriptions)
        if self._long_term is not None or self._milestone is not None:
            recall = MemoryRecallAction(
                long_term=self._long_term,
                milestone=self._milestone,
            )
            self._executor.register_instance(recall)
            effective_descriptions[recall.name] = recall.description

        # Inject KB tools when a knowledge config is provided.
        self._kb = None
        if cfg.knowledge is not None:
            from knowledge import KnowledgeBase
            self._kb = KnowledgeBase.from_config(cfg.knowledge)
            self._kb.setup()

            kb_search = KnowledgeHybridSearchAction(kb=self._kb)
            kb_save   = KnowledgeSaveAction(kb=self._kb)
            kb_list   = KnowledgeListAction(kb=self._kb)
            for action in (kb_search, kb_save, kb_list):
                self._executor.register_instance(action)
                effective_descriptions[action.name] = action.description

            web_search_inst = WebSearchAction()
            web_fetch_inst  = WebFetchAction()
            skill = DomainLearningSkill(
                llm=self._llm,
                kb=self._kb,
                web_search=web_search_inst,
                web_fetch=web_fetch_inst,
            )
            self._executor.register_instance(skill)
            effective_descriptions[skill.name] = skill.description

        # Inject scheduler tools when a scheduler config is provided.
        self._scheduler_engine = None
        if cfg.scheduler is not None:
            from scheduler.engine import SchedulerEngine
            from react.action.tools.impl.scheduler_add import SchedulerAddAction
            from react.action.tools.impl.scheduler_list import SchedulerListAction
            from react.action.tools.impl.scheduler_cancel import SchedulerCancelAction
            self._scheduler_engine = SchedulerEngine(cfg.scheduler)
            for action in (
                SchedulerAddAction(engine=self._scheduler_engine),
                SchedulerListAction(engine=self._scheduler_engine),
                SchedulerCancelAction(engine=self._scheduler_engine),
            ):
                self._executor.register_instance(action)
                effective_descriptions[action.name] = action.description

        self._manager = PromptManager(effective_descriptions, cfg.prompt, tool_category_summary)

        # Pre-assembled static prompt parts for the next turn.
        # None on first turn; rebuilt in post_process() after each commit.
        self._static_cache: StaticPromptParts | None = None

        # Commit payload set inside stream() and consumed by post_process().
        self._pending_finish: _PendingFinish | None = None

        # Repair LLM: falls back to the main LLM when no dedicated config is given.
        self._repair_llm = (
            LLMHandle(LLM(cfg.repair_llm)) if cfg.repair_llm is not None else self._llm
        )

    @staticmethod
    def _trunc(text: str, limit: int) -> str:
        return text[:limit] if limit > 0 and len(text) > limit else text

    # ── Core streaming loop ───────────────────────────────────────────────────

    def stream(self, question: str) -> Generator[TaoEvent, None, None]:
        question = self._trunc(question, self._cfg.prompt.max_question_chars)
        processor = MemoryProcessor(
            self._cfg.memory,
            self._llm,
            long_term=self._long_term,
            milestone=self._milestone,
            medium_term=self._medium_term,
        )

        # 短期偏好对 L3 的检索偏置（使用上一轮更新后的偏好，偏置当前轮召回）
        recall_query = (
            self._persona.bias_query(question)
            if self._persona is not None
            else question
        )

        # Long-term recall result cached after step 0 (expensive vector search
        # is only run once per question, reused for subsequent ReAct steps).
        _cached_lt: str = ""
        _cached_milestone: str = ""

        for i in range(self._cfg.max_steps):
            # ── Memory recall ────────────────────────────────────────────────
            # Long-term search only at step 0; subsequent steps reuse the result.
            result = processor.recall(recall_query, include_long_term=(i == 0))
            if i == 0:
                _cached_lt = result.long_term
                _cached_milestone = result.milestone

            # ── Persona blocks ───────────────────────────────────────────────
            persona_blocks: list[PromptBlock] | None = (
                self._persona.all_blocks() if self._persona is not None else None
            )

            # ── Message assembly ─────────────────────────────────────────────
            # Each memory tier is passed as a separate labeled slot; the
            # manager renders independent section headers for each.
            if self._static_cache is not None:
                messages = self._manager.build_messages_from_static(
                    self._static_cache,
                    question=question,
                    long_term=_cached_lt,
                    medium_term=result.medium_term,
                    milestone=_cached_milestone,
                    short_term=result.short_term,
                    short_term_distillate=result.short_term_distillate,
                )
            else:
                # First turn or cache invalidated — full build path.
                messages = self._manager.build_messages(
                    question,
                    MemoryResult(
                        short_term=result.short_term,
                        short_term_distillate=result.short_term_distillate,
                        medium_term=result.medium_term,
                        long_term=_cached_lt,
                        milestone=_cached_milestone,
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

            # ── Three-layer parse robustness ──────────────────────────────────
            # tool_names is passed to the parser to enable lenient inference.
            tool_names = frozenset(self._executor.available_actions)
            result = parse_llm_output(raw_output, tool_names=tool_names)

            # Layer 2: repair LLM — only triggered on a hard FAILED parse that
            # is NOT already being treated as an implicit finish.
            if (
                result.quality == ParseQuality.FAILED
                and not result.is_finish
                and self._cfg.prompt.repair_enabled
            ):
                _diagnosis = diagnose(result)
                _repaired = repair(
                    self._repair_llm,
                    raw_output,
                    _diagnosis,
                    list(tool_names),
                )
                if _repaired:
                    result = parse_llm_output(_repaired, tool_names=tool_names)

            # Layer 0: inject a correction message and retry the main LLM.
            # Only runs when both Layer 1 and Layer 2 failed to recover.
            if result.quality == ParseQuality.FAILED and not result.is_finish:
                for _attempt in range(self._cfg.prompt.retry_on_bad_parse):
                    yield RetryEvent(index=i, reason=diagnose(result))
                    correction_msgs = messages + [
                        AIMessage(content=raw_output),
                        HumanMessage(content=(
                            "格式有误，请严格按照以下格式重新输出：\n"
                            "Thought: <思考过程>\n"
                            "Action: <工具名>\n"
                            'Action Input: {"key": "value"}'
                        )),
                    ]
                    raw_output = ""
                    for chunk in self._llm.stream_generate_messages(correction_msgs):
                        raw_output += chunk
                        yield ChunkEvent(index=i, chunk=chunk)
                    result = parse_llm_output(raw_output, tool_names=tool_names)
                    if result.quality != ParseQuality.FAILED or result.is_finish:
                        break
                # All three layers exhausted — result is an implicit finish
                # (action="" path in the parser), which is the safest degradation.

            if result.is_finish:
                answer = result.action_input.get("answer", raw_output)

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
                json.dumps({"action": result.action, "args": result.action_input}, ensure_ascii=False)
            )
            observation = self._trunc(observation, self._cfg.prompt.max_observation_chars)

            step = Step(
                thought=result.thought,
                action=result.action,
                action_input=result.action_input,
                observation=observation,
            )
            processor.add(step)

            yield StepEvent(
                index=i,
                thought=result.thought,
                action=result.action,
                action_input=result.action_input,
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
            extra_system_blocks=pf.persona_blocks,
        )

    # ── Misc ─────────────────────────────────────────────────────────────────

    def preload(self) -> None:
        """触发长期记忆的后台预热（嵌入模型 + FAISS 索引）。"""
        if self._long_term is not None:
            self._long_term.store.preload()

    def update_llm(self, llm: LLM) -> None:
        """Swap the underlying LLM for every component in this TaoLoop.

        Because all sub-components share the same LLMHandle, a single call
        here propagates instantly — no chain of per-component update calls.
        """
        self._llm.update(llm)

    def reset(self) -> None:
        self._manager.clear_history()
        self._static_cache = None
        self._pending_finish = None

    def clear_memory(self) -> None:
        """Wipe all persistent memory tiers and reset in-memory state."""
        import os

        self.reset()

        memory_dir    = self._cfg.memory.long_term.memory_dir
        medium_dir    = self._cfg.memory.medium_term.memory_dir
        milestone_dir = self._cfg.memory.milestone.milestone_dir

        targets = [
            os.path.join(memory_dir,    "memories.json"),
            os.path.join(memory_dir,    "memory_index.faiss"),
            os.path.join(medium_dir,    "medium_term.jsonl"),
            os.path.join(milestone_dir, "milestones.json"),
        ]
        for fpath in targets:
            if fpath and os.path.exists(fpath):
                os.remove(fpath)

        # Reset in-memory state of live objects
        if self._long_term is not None:
            self._long_term.store._entries.clear()
            self._long_term.store._vectorstore = None
        if self._milestone is not None:
            self._milestone._store._entries.clear()
        if self._medium_term is not None:
            self._medium_term._entries.clear()

    def clear_persona(self) -> None:
        """删除人格漂移数据（profile / skills / reflection / preference），重置内存状态。"""
        if self._persona is None:
            raise RuntimeError("Persona not enabled.")
        self._persona.clear_drift()

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
