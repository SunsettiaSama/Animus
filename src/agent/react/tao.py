from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Generator, Union

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from config.agent.tao_config import TaoConfig
from infra.sandbox import SandboxManager
from infra.llm import LLM, LLMHandle
from .action.executor import ActionExecutor
from .action.risk.gate import RiskGate
from .action.risk.level import RiskLevel
from .action.tools.impl.memory_recall import MemoryRecallAction
from .action.tools.impl.knowledge_hybrid_search import KnowledgeHybridSearchAction
from .action.tools.impl.knowledge_save import KnowledgeSaveAction
from .action.tools.impl.knowledge_list import KnowledgeListAction
from .action.tools.impl.scratchpad import NoteDeleteAction, NoteReadAction, NoteWriteAction, ScratchpadStore
from .action.skill.domain_learning import DomainLearningSkill
from .action.tools.impl.web_fetch import WebFetchAction
from .action.tools.impl.web_search import WebSearchAction
from .memory.long_term.init import make_memory
from .memory.long_term.memory import LongTermMemory
from .memory.medium_term.memory import RecentHistoryMemory
from .memory.memory import Step
from .memory.milestone.init import make_milestone
from .memory.milestone.memory import MilestoneMemory
from .memory.processor import MemoryProcessor, MemoryResult
from .prompt.block import MemoryBlock, PromptBlock
from .prompt.parser import ParseQuality, diagnose, parse_llm_output
from .prompt.repair import repair
from .persona import PersonaManager
from .prompt.manager import PromptManager, StaticPromptParts
from .trace import TraceStore
from agent.scheduler.timeline import TimelineStore


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
class MaxStepsEvent:
    """Yielded when the step loop exhausts max_steps without a finish action.

    Distinct from an error so the frontend can display a clear "step limit
    reached" message instead of showing the generic "⊘ aborted" state.
    """
    max_steps: int


@dataclass
class RetryEvent:
    index: int
    reason: str


@dataclass
class ApprovalRequestEvent:
    request_id: str
    tool_name: str
    args: dict
    risk_level: str
    reason: str
    deadline_secs: int


@dataclass
class SubAgentStartEvent:
    action: str
    instruction: str


@dataclass
class SubAgentChunkEvent:
    index: int
    chunk: str


@dataclass
class SubAgentStepEvent:
    index: int
    thought: str
    action: str
    action_input: dict
    observation: str
    is_error: bool = False


@dataclass
class SubAgentFinishEvent:
    answer: str


@dataclass
class SubAgentErrorEvent:
    error: str


TaoEvent = Union[
    StepStartEvent, ChunkEvent, StepEvent, FinishEvent,
    PromptPreviewEvent, RetryEvent, ApprovalRequestEvent,
    SubAgentStartEvent, SubAgentChunkEvent, SubAgentStepEvent,
    SubAgentFinishEvent, SubAgentErrorEvent,
]


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
        llm: LLMHandle,
        executor: ActionExecutor,
        tool_descriptions: dict[str, str],
        cfg: TaoConfig,
        tool_category_summary: str = "",
        sandbox: SandboxManager | None = None,
        risk_gate: RiskGate | None = None,
    ):
        self._llm = llm   # canonical handle from LLMService — shared by all sub-components
        self._executor = executor
        self._cfg = cfg
        self._sandbox = sandbox
        self._risk_gate = risk_gate
        self._trace_store: TraceStore | None = (
            TraceStore(cfg.trace) if cfg.trace.enabled else None
        )
        self._persona: PersonaManager | None = (
            PersonaManager(cfg.persona, llm=self._llm) if cfg.persona.enabled else None
        )

        # Timeline store — always created; writes are no-ops until directory exists.
        self._timeline = TimelineStore(cfg.storage.timeline_dir)

        # Abort signal — set by abort(), cleared by reset() / rollback_turn()
        self._stop_event = threading.Event()

        # Sub-agent event sink — set by the WS router to forward nested events.
        self._sub_event_sink = None

        # Approval gate state: maps request_id → (threading.Event, approved: bool | None)
        self._pending_approvals: dict[str, threading.Event] = {}
        self._approval_results: dict[str, bool] = {}
        self._approval_lock = threading.Lock()

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

        # Inject scratchpad tools (always active; stateful, session-scoped).
        self._scratchpad = ScratchpadStore()
        for action in (
            NoteWriteAction(store=self._scratchpad),
            NoteReadAction(store=self._scratchpad),
            NoteDeleteAction(store=self._scratchpad),
        ):
            self._executor.register_instance(action)
            effective_descriptions[action.name] = action.description

        # Inject sandbox-dependent tools when a sandbox is available.
        if self._sandbox is not None:
            from .action.tools.impl.file_system import (
                FileReadAction, FileWriteAction, FileListAction, FileExistsAction,
            )
            from .action.tools.impl.http_request import HttpRequestAction
            from .action.tools.impl.python_run import PythonRunAction
            for action in (
                FileReadAction(sandbox=self._sandbox),
                FileWriteAction(sandbox=self._sandbox),
                FileListAction(sandbox=self._sandbox),
                FileExistsAction(sandbox=self._sandbox),
                HttpRequestAction(sandbox=self._sandbox),
                PythonRunAction(sandbox=self._sandbox),
            ):
                self._executor.register_instance(action)
                effective_descriptions[action.name] = action.description

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

            # Inject research and document summary skills.
            from .action.skill.research import WebResearchSkill
            from .action.skill.document_summary import DocumentSummarySkill
            research_skill = WebResearchSkill(
                llm=self._llm,
                web_search=web_search_inst,
                web_fetch=web_fetch_inst,
            )
            self._executor.register_instance(research_skill)
            effective_descriptions[research_skill.name] = research_skill.description

            if self._sandbox is not None:
                from .action.tools.impl.file_system import FileReadAction as _FR
                doc_summary_skill = DocumentSummarySkill(
                    llm=self._llm,
                    file_read=_FR(sandbox=self._sandbox),
                )
                self._executor.register_instance(doc_summary_skill)
                effective_descriptions[doc_summary_skill.name] = doc_summary_skill.description

        # Inject scheduler tools when a scheduler config is provided.
        self._scheduler_engine = None
        if cfg.scheduler is not None:
            from agent.scheduler.engine import SchedulerEngine
            from .action.tools.impl.scheduler_add import SchedulerAddAction
            from .action.tools.impl.scheduler_list import SchedulerListAction
            from .action.tools.impl.scheduler_cancel import SchedulerCancelAction
            self._scheduler_engine = SchedulerEngine(
                cfg.scheduler,
                long_term=self._long_term,
                timeline=self._timeline,
            )
            for action in (
                SchedulerAddAction(engine=self._scheduler_engine),
                SchedulerListAction(engine=self._scheduler_engine),
                SchedulerCancelAction(engine=self._scheduler_engine),
            ):
                self._executor.register_instance(action)
                effective_descriptions[action.name] = action.description

        # Inject delegate_task skill when an agent config is provided.
        self._delegate_skill = None
        if cfg.agent is not None:
            from agent.runner import SubAgentRunner
            from .action.skill.delegate_task import DelegateTaskSkill
            delegate_skill = DelegateTaskSkill(
                runner=SubAgentRunner(),
                cfg=cfg.agent,
            )
            self._delegate_skill = delegate_skill
            self._executor.register_instance(delegate_skill)
            effective_descriptions[delegate_skill.name] = delegate_skill.description

        # Inject plan skills when a plan config is provided.
        self._plan_orchestrator = None
        self._plan_skill_set = None
        if cfg.plan is not None:
            from plan.orchestrator import PlanOrchestrator
            from .action.skill.plan_skill import (
                PlanSkillSet,
                RunPlanSkill,
                PlanStatusSkill,
                PlanWaitSkill,
                PlanSkipSkill,
            )
            self._plan_orchestrator = PlanOrchestrator(
                cfg=cfg.plan.orchestrator,
                llm_cfg_path=cfg.plan.llm_cfg_path,
                agent_cfg=getattr(cfg.plan, "agent", None),
            )
            # Wire PlanEvent -> TimelineStore so plan events appear on the session timeline.
            import dataclasses as _dc
            def _plan_event_to_timeline(event: object) -> None:
                self._timeline.append("plan_event", {
                    "type": type(event).__name__,
                    **_dc.asdict(event),  # type: ignore[arg-type]
                })
            self._plan_orchestrator.subscribe(_plan_event_to_timeline)

            self._plan_skill_set = PlanSkillSet(
                orchestrator=self._plan_orchestrator,
                event_sink=None,  # injected later via set_plan_event_sink()
            )
            for skill in (
                RunPlanSkill(skill_set=self._plan_skill_set),
                PlanStatusSkill(skill_set=self._plan_skill_set),
                PlanWaitSkill(skill_set=self._plan_skill_set),
                PlanSkipSkill(skill_set=self._plan_skill_set),
            ):
                # Register instance for execution; intentionally NOT added to
                # effective_descriptions so plan tools are only discovered via
                # tool_search, not shown in the primary tool list.
                self._executor.register_instance(skill)

        # Hook the tool-layer event sink after all tools are registered.
        self._executor.set_event_sink(self._timeline.make_tool_sink())

        # Build PromptManager after all tools are registered so the complete
        # effective_descriptions dict (including injected tools) is available.
        self._manager = PromptManager(
            effective_descriptions,
            cfg=cfg.prompt,
            tool_category_summary=tool_category_summary,
        )

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

    @property
    def scheduler_engine(self):
        return self._scheduler_engine

    @property
    def timeline(self) -> TimelineStore:
        return self._timeline

    @property
    def sub_event_sink(self):
        return self._sub_event_sink

    @sub_event_sink.setter
    def sub_event_sink(self, sink):
        self._sub_event_sink = sink
        if self._delegate_skill is not None:
            self._delegate_skill.sub_event_sink = sink

    def set_plan_event_sink(self, sink) -> None:
        """Inject an event_sink into the PlanSkillSet (called by WebUI after init)."""
        if self._plan_skill_set is not None:
            self._plan_skill_set.set_event_sink(sink)

    # ── Approval gate ─────────────────────────────────────────────────────────

    def resolve_approval(self, request_id: str, approved: bool) -> bool:
        """
        Called by the WebSocket handler when the user responds to an approval request.

        Sets the corresponding threading.Event so the waiting stream() can resume.
        Returns True if the request_id was found and resolved, False otherwise.
        """
        with self._approval_lock:
            event = self._pending_approvals.get(request_id)
            if event is None:
                return False
            self._approval_results[request_id] = approved
        event.set()
        return True

    # ── Core streaming loop ───────────────────────────────────────────────────

    def stream(self, question: str) -> Generator[TaoEvent, None, None]:
        import time as _time
        from test.obs.collector import get_collector as _get_collector
        from test.obs.events import ParseEvent as _ParseEvent, SessionEvent as _SessionEvent, ToolCallEvent as _ToolCallEvent

        _obs = _get_collector()
        _session_id = str(uuid.uuid4())
        _obs.set_session(_session_id)
        _obs.emit(_SessionEvent(
            session_id=_session_id,
            ts=_time.time(),
            event_type="start",
            question_summary=question[:200],
            total_steps=0,
            answer_summary="",
        ))

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

        # ── Per-question caches ───────────────────────────────────────────────
        # These three tiers don't change while a question's step loop is running
        # (updates only happen in post_process() after the turn ends).
        # Caching them here avoids repeated vector searches, JSONL reads, and
        # persona file I/O on every step.
        _cached_lt: str = ""
        _cached_milestone: str = ""
        _cached_medium: str = ""

        # Persona blocks are also stable across steps.
        persona_blocks: list[PromptBlock] | None = (
            self._persona.all_blocks() if self._persona is not None else None
        )

        for i in range(self._cfg.max_steps):
            # ── Memory recall ────────────────────────────────────────────────
            if i == 0:
                # Full recall on step 0: long-term vector search + milestone
                # retrieval + medium-term render.  Results are cached for
                # all subsequent steps in this question.
                result = processor.recall(recall_query, include_long_term=True)
                _cached_lt        = result.long_term
                _cached_milestone = result.milestone
                _cached_medium    = result.medium_term
            else:
                # Steps > 0: only short-term memory grows (new tool observations
                # are appended via processor.add()).  Reuse cached values for the
                # other tiers to skip repeated vector searches and file reads.
                _short = processor.recall_short_term()
                result = MemoryResult(
                    short_term=_short.short_term,
                    short_term_distillate=_short.short_term_distillate,
                    medium_term=_cached_medium,
                    long_term=_cached_lt,
                    milestone=_cached_milestone,
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

            # ── Active plan status injection ─────────────────────────────────
            # If a plan is running, append a compact status block to the system
            # message so the agent is aware of ongoing background progress.
            if (
                self._plan_orchestrator is not None
                and self._plan_orchestrator.lifecycle_state.value
                    not in ("idle", "done", "failed", "aborted")
            ):
                from .action.skill.plan_skill import _format_plan_status
                plan_status_block = (
                    "\n\n【活跃多智能体计划】\n"
                    + _format_plan_status(self._plan_orchestrator)
                )
                if messages and isinstance(messages[0], SystemMessage):
                    messages[0] = SystemMessage(
                        content=messages[0].content + plan_status_block
                    )

            # ── Prompt preview (step 0 only) ─────────────────────────────────
            # Build the preview payload eagerly but defer the yield until after
            # the first LLM chunk arrives.  This ensures TTFB is not blocked by
            # serialising a potentially large system message over WebSocket.
            if i == 0:
                _preview: list[dict] = []
                for msg in messages:
                    if isinstance(msg, SystemMessage):
                        _preview.append({"role": "system", "content": msg.content})
                    elif isinstance(msg, HumanMessage):
                        _preview.append({"role": "user", "content": msg.content})
                    elif isinstance(msg, AIMessage):
                        _preview.append({"role": "assistant", "content": msg.content})
            else:
                _preview = []

            yield StepStartEvent(index=i)

            # ── LLM generation ───────────────────────────────────────────────
            raw_output = ""
            _preview_sent = (i != 0)   # only step 0 has a preview to send
            for chunk in self._llm.stream_generate_messages(messages):
                if self._stop_event.is_set():
                    return
                raw_output += chunk
                if not _preview_sent:
                    # First token is now in-flight — safe to send the preview.
                    yield PromptPreviewEvent(messages=_preview)
                    _preview_sent = True
                yield ChunkEvent(index=i, chunk=chunk)

            # ── Parse robustness — escalation chain ───────────────────────────
            # Escalation order (cheapest → most expensive):
            #   L1  strict regex + L1b lenient inference  (parser, free)
            #   L2  in-context correction retry            (main LLM, 1 call per attempt)
            #   L3  isolated repair LLM                   (separate call, no conversation ctx)
            #   L4  safe degradation → implicit finish
            tool_names = frozenset(self._executor.available_actions)
            result = parse_llm_output(raw_output, tool_names=tool_names)

            # L2: in-context correction — inject a bilingual format reminder into
            # the existing conversation and retry the main LLM.  Runs first
            # because the model already has full context and self-correction is
            # cheapest before we resort to an isolated repair call.
            # Also triggers for FINISH_DEGRADED: finish was detected but the
            # Action Input JSON could not be parsed, so the answer fell back to
            # Thought or raw text.  A targeted reminder asking for double-quoted
            # JSON is usually enough for the model to self-correct.
            def _needs_retry(r: "ParseResult") -> bool:  # type: ignore[name-defined]
                return (
                    r.quality == ParseQuality.FAILED and not r.is_finish
                ) or r.quality == ParseQuality.FINISH_DEGRADED

            if _needs_retry(result):
                for _attempt in range(self._cfg.prompt.retry_on_bad_parse):
                    _retry_reason = diagnose(result)
                    yield RetryEvent(index=i, reason=_retry_reason)
                    _obs.emit(_ParseEvent(
                        session_id=_session_id,
                        ts=_time.time(),
                        step_index=i,
                        event_type="retry_l2",
                        diagnosis=_retry_reason,
                    ))
                    # Use a finish-specific correction when the problem is only
                    # the JSON encoding of the answer, not the overall structure.
                    if result.quality == ParseQuality.FINISH_DEGRADED:
                        _correction = (
                            "Your Action Input is not valid JSON. "
                            "Since you want to finish, please rewrite using double-quoted JSON:\n"
                            "Thought: <your reasoning>\n"
                            "Action: finish\n"
                            'Action Input: {"answer": "your complete answer here"}\n\n'
                            "Action Input 不是合法 JSON（请使用双引号）。请按以下格式重新输出 finish：\n"
                            "Thought: <思考过程>\n"
                            "Action: finish\n"
                            'Action Input: {"answer": "完整回答内容"}'
                        )
                    else:
                        _correction = (
                            "Your output format is incorrect. Please rewrite strictly following this format:\n"
                            "Thought: <your reasoning>\n"
                            "Action: <tool_name>\n"
                            'Action Input: {"key": "value"}\n\n'
                            "格式有误，请严格按照以下格式重新输出：\n"
                            "Thought: <思考过程>\n"
                            "Action: <工具名>\n"
                            'Action Input: {"key": "value"}'
                        )
                    correction_msgs = messages + [
                        AIMessage(content=raw_output),
                        HumanMessage(content=_correction),
                    ]
                    raw_output = ""
                    for chunk in self._llm.stream_generate_messages(correction_msgs):
                        if self._stop_event.is_set():
                            return
                        raw_output += chunk
                        yield ChunkEvent(index=i, chunk=chunk)
                    result = parse_llm_output(raw_output, tool_names=tool_names)
                    if not _needs_retry(result):
                        break

            # L3: isolated repair LLM — only reached when all in-context retries
            # failed.  Calls the repair model with a focused reformat prompt
            # (no conversation history) and verifies the result re-parses before
            # accepting it.  Also covers FINISH_DEGRADED where L2 could not coax
            # the model into producing valid Action Input JSON.
            if (
                _needs_retry(result)
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
                    _obs.emit(_ParseEvent(
                        session_id=_session_id,
                        ts=_time.time(),
                        step_index=i,
                        event_type="repair_l3",
                        diagnosis=_diagnosis,
                    ))
                    result = parse_llm_output(_repaired, tool_names=tool_names)

            # L4: all layers exhausted — the parser's implicit-finish path
            # (action="" branch) is the safest degradation; the LLM's raw
            # output (or thought) is surfaced as the answer.

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
                _obs.emit(_SessionEvent(
                    session_id=_session_id,
                    ts=_time.time(),
                    event_type="finish",
                    question_summary=question[:200],
                    total_steps=i + 1,
                    answer_summary=answer[:200],
                ))
                return

            # ── Tool execution ───────────────────────────────────────────────
            action_json = json.dumps(
                {"action": result.action, "args": result.action_input},
                ensure_ascii=False,
            )
            _t_tool_start = _time.perf_counter()

            # ── Risk gate check ──────────────────────────────────────────────
            if self._risk_gate is not None and self._risk_gate.cfg.enabled:
                risk = self._risk_gate.check(result.action, result.action_input)
                if self._risk_gate.requires_approval(risk):
                    request_id = str(uuid.uuid4())
                    event = threading.Event()
                    with self._approval_lock:
                        self._pending_approvals[request_id] = event

                    timeout_secs = self._risk_gate.cfg.approval_timeout_secs
                    yield ApprovalRequestEvent(
                        request_id=request_id,
                        tool_name=result.action,
                        args=result.action_input,
                        risk_level=risk.level.value,
                        reason=risk.reason,
                        deadline_secs=timeout_secs,
                    )

                    granted = event.wait(timeout=timeout_secs)
                    with self._approval_lock:
                        self._pending_approvals.pop(request_id, None)
                        approved = self._approval_results.pop(request_id, False)

                    if not granted or not approved:
                        label = "超时未响应" if not granted else "用户拒绝"
                        observation = f"[{label}] 操作 {result.action!r} 未获批准，已取消执行。"
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
                        continue

            observation = self._executor.run(action_json)
            observation = self._trunc(observation, self._cfg.prompt.max_observation_chars)

            _t_tool_end = _time.perf_counter()
            _obs.emit(_ToolCallEvent(
                session_id=_session_id,
                ts=_t_tool_start,
                step_index=i,
                tool_name=result.action,
                latency_ms=(_t_tool_end - _t_tool_start) * 1000,
                input_summary=action_json[:200],
                output_summary=observation[:200],
            ))

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

        yield MaxStepsEvent(max_steps=self._cfg.max_steps)
        _obs.emit(_SessionEvent(
            session_id=_session_id,
            ts=_time.time(),
            event_type="max_steps",
            question_summary=question[:200],
            total_steps=self._cfg.max_steps,
            answer_summary="",
        ))

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

        self._timeline.append("conversation", {
            "q": pf.question[:300],
            "a": pf.answer[:500],
        })

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

    def close(self) -> None:
        if self._long_term is not None:
            self._long_term.store.close()

    def update_llm(self, llm: LLM) -> None:
        self._llm.update(llm)

    def abort(self) -> None:
        """Signal the running stream() generator to stop at the next chunk boundary."""
        self._stop_event.set()

    def rollback_turn(self) -> None:
        """Discard the unfinished current turn without clearing conversation history."""
        self._pending_finish = None
        self._static_cache = None
        self._stop_event.clear()

    def reset(self) -> None:
        self._manager.clear_history()
        self._static_cache = None
        self._pending_finish = None
        self._scratchpad.reset()
        self._stop_event.clear()

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
            if isinstance(event, MaxStepsEvent):
                raise RuntimeError(
                    f"TaoLoop exceeded max_steps={event.max_steps} without finishing"
                )
        raise RuntimeError(f"TaoLoop exhausted stream without FinishEvent")

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
