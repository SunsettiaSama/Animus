from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Generator, Union

logger = logging.getLogger(__name__)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # SystemMessage used for format corrections

from config.agent.tao_config import TaoConfig
from infra.sandbox import SandboxManager
from infra.llm import LLM, LLMHandle
from .action.executor import ActionExecutor
from .action.risk.gate import RiskGate
from .action.risk.level import RiskLevel
from .action.tools.impl.knowledge_hybrid_search import KnowledgeHybridSearchAction
from .action.tools.impl.knowledge_save import KnowledgeSaveAction
from .action.tools.impl.knowledge_list import KnowledgeListAction
from .action.tools.impl.scratchpad import NoteDeleteAction, NoteReadAction, NoteWriteAction, ScratchpadStore
from .action.skill.domain_learning import DomainLearningSkill
from .action.tools.impl.web_fetch import WebFetchAction
from .action.tools.impl.web_search import WebSearchAction
from .context.medium_term.memory import RecentHistoryMemory
from .context.memory import Step
from agent.soul.memory.service import MemoryService
from .context.processor import MemoryProcessor, MemoryResult
from .prompt.block import MemoryBlock, PromptBlock
from .prompt.parser import ParseQuality, ParseResult, diagnose, parse_llm_output
from .prompt.repair import repair
from agent.soul.life import JournalBlock, LifeManager, LifeProfileBlock
from agent.soul import SoulConfig, SoulService
from agent.soul.persona import PersonaService
from .prompt.manager import PromptManager, StaticPromptParts
from .trace import TraceStore
from runtime.scheduler.timeline_service import TimelineService


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
    calls: list[dict] | None = None  # [{"action": str, "args": dict}, ...] for parallel steps
    output: str = ""                  # <O> tag content; user-visible output for this step


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
        scheduler_engine=None,
        reply_target: dict | None = None,
        notify_fn=None,
        comm_rate_cfg=None,
        llm_service=None,
        soul_service: SoulService | None = None,
    ):
        if cfg.persona.enabled and cfg.db is None:
            raise ValueError(
                "Soul 已启用（persona.enabled）但未配置 TaoConfig.db"
            )

        self._llm = llm   # canonical handle from LLMService — shared by all sub-components
        self._executor = executor
        self._cfg = cfg
        self._sandbox = sandbox
        self._risk_gate = risk_gate
        self._trace_store: TraceStore | None = (
            TraceStore(cfg.trace) if cfg.trace.enabled else None
        )
        self._persona: PersonaService | None = None

        # Soul 子系统 — 可注入已有 SoulService，或在 persona 启用时自建
        self._soul: SoulService | None = soul_service
        self._life: LifeManager | None = None
        self._soul_memory: MemoryService | None = None
        if self._soul is not None:
            self._persona = self._soul.persona.service
            self._life = self._soul.life.api
            self._soul_memory = self._soul.memory.api
        elif cfg.persona.enabled:
            _backend = cfg.db.resolved_storage_backend()
            _mysql = None
            if _backend == "mysql" and not cfg.db.mysql.enabled:
                raise ValueError(
                    "Soul storage backend=mysql，但 MySQL 未启用（config/infra/db.yaml）"
                )
            if _backend == "mysql":
                _mysql = cfg.db.mysql.build_client()
            self._soul = SoulService(
                life_dir=cfg.storage.life_dir,
                persona_cfg=cfg.persona,
                mysql_client=_mysql,
                llm_service=llm_service,
                primary_llm=self._llm,
                cfg=SoulConfig.load_default(),
                db_cfg=cfg.db,
                storage_backend=_backend,
                json_root=cfg.db.storage.json_root,
            )
            self._soul.start()
            self._persona = self._soul.persona.service
            self._life = self._soul.life.api
            self._soul_memory = self._soul.memory.api

        # 时间轴仅经 TimelineService 读写，与调度/心跳隔离。
        self._timeline = TimelineService(cfg.storage.timeline_dir)

        # Abort signal — set by abort(), cleared by reset() / rollback_turn()
        self._stop_event = threading.Event()

        # Sub-agent event sink — set by the WS router to forward nested events.
        self._sub_event_sink = None

        # Approval gate state: maps request_id → threading.Event
        self._pending_approvals: dict[str, threading.Event] = {}
        self._approval_results: dict[str, bool] = {}
        self._approval_lock = threading.Lock()

        self._medium_term: RecentHistoryMemory | None = (
            RecentHistoryMemory(cfg.memory.medium_term, llm=self._llm)
            if cfg.memory.medium_term.enabled
            else None
        )

        if self._life is not None and self._soul_memory is not None:
            self._life.set_memory_port(self._soul_memory.life_port)

        effective_descriptions = dict(tool_descriptions)
        if self._soul is not None:
            from agent.adapters.soul_tao.tools import register_soul_tools
            register_soul_tools(self._executor, self._soul, effective_descriptions)

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
            web_fetch_inst  = WebFetchAction(sandbox=self._sandbox)
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

            from .action.skill.github_trending_report import GitHubTrendingReportSkill
            from .action.skill.arxiv_frontier_report import ArxivFrontierReportSkill
            from .action.skill.frontier_report import FrontierReportSkill
            gh_skill = GitHubTrendingReportSkill(
                llm=self._llm,
                web_fetch=web_fetch_inst,
            )
            self._executor.register_instance(gh_skill)
            effective_descriptions[gh_skill.name] = gh_skill.description
            arxiv_skill = ArxivFrontierReportSkill(
                llm=self._llm,
                web_fetch=web_fetch_inst,
            )
            self._executor.register_instance(arxiv_skill)
            effective_descriptions[arxiv_skill.name] = arxiv_skill.description
            frontier_skill = FrontierReportSkill(
                llm=self._llm,
                web_fetch=web_fetch_inst,
            )
            self._executor.register_instance(frontier_skill)
            effective_descriptions[frontier_skill.name] = frontier_skill.description

            if self._sandbox is not None:
                from .action.tools.impl.file_system import FileReadAction as _FR
                doc_summary_skill = DocumentSummarySkill(
                    llm=self._llm,
                    file_read=_FR(sandbox=self._sandbox),
                )
                self._executor.register_instance(doc_summary_skill)
                effective_descriptions[doc_summary_skill.name] = doc_summary_skill.description

        # Inject scheduler tools.
        # Prefer a pre-built global engine (scheduler_engine kwarg); fall back to
        # creating one from cfg.scheduler if no global engine was provided.
        self._scheduler_engine = None
        _engine_to_use = scheduler_engine
        if _engine_to_use is None and cfg.scheduler is not None:
            from runtime.scheduler.engine import SchedulerEngine
            from agent.soul.heartbeat.task_runner import TaskRunner
            _runner = TaskRunner(
                cfg=cfg.scheduler,
                timeline=self._timeline,
            )
            _engine_to_use = SchedulerEngine(
                cfg.scheduler,
                executor=_runner,
            )
            _runner._engine = _engine_to_use
        if _engine_to_use is not None:
            from .action.tools.impl.scheduler_add import SchedulerAddAction
            from .action.tools.impl.scheduler_list import SchedulerListAction
            from .action.tools.impl.scheduler_cancel import SchedulerCancelAction
            from .action.tools.impl.timeline_read import TimelineReadAction
            self._scheduler_engine = _engine_to_use
            for action in (
                SchedulerAddAction(engine=self._scheduler_engine, reply_target=reply_target),
                SchedulerListAction(engine=self._scheduler_engine),
                SchedulerCancelAction(engine=self._scheduler_engine),
                TimelineReadAction(timeline=self._timeline),
            ):
                self._executor.register_instance(action)
                effective_descriptions[action.name] = action.description

        # Inject notify_user tool when a mid-run notification callback is provided.
        # This path is independent of scheduler_engine injection.
        if notify_fn is not None:
            from .action.tools.impl.notify_user import NotifyUserAction
            _notify_action = NotifyUserAction(notify_fn=notify_fn)
            self._executor.register_instance(_notify_action)
            effective_descriptions[_notify_action.name] = _notify_action.description

        # Inject communication atomic tools when rate config is provided.
        if comm_rate_cfg is not None:
            from webui.state import get_state as _get_state
            _st = _get_state()
            if _st.bark_notifier is not None or _st.ntfy_notifier is not None:
                from .action.tools.impl.send_notification import SendNotificationAction
                _sn = SendNotificationAction(rate_cfg=comm_rate_cfg)
                self._executor.register_instance(_sn)
                effective_descriptions[_sn.name] = _sn.description
            if _st.bot_service is not None:
                from .action.tools.impl.send_bot_message import SendBotMessageAction
                _sb = SendBotMessageAction(
                    bot_service=_st.bot_service,
                    main_event_loop=_st.main_event_loop,
                    rate_cfg=comm_rate_cfg,
                )
                self._executor.register_instance(_sb)
                effective_descriptions[_sb.name] = _sb.description

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

        # Inject flow skills when a flow config is provided.
        self._flow_orchestrator = None
        self._flow_skill_set = None
        if cfg.flow is not None:
            from agent.flow.cluster.orchestrator import FlowOrchestrator
            from .action.skill.flow_skill import (
                FlowSkillSet,
                RunFlowSkill,
                FlowStatusSkill,
                FlowWaitSkill,
                FlowSkipSkill,
            )
            self._flow_orchestrator = FlowOrchestrator(
                cfg=cfg.flow.orchestrator,
                llm_cfg_path=cfg.flow.llm_cfg_path,
                agent_cfg=getattr(cfg.flow, "agent", None),
            )
            import dataclasses as _dc
            def _flow_event_to_timeline(event: object) -> None:
                self._timeline.append("flow_event", {
                    "type": type(event).__name__,
                    **_dc.asdict(event),  # type: ignore[arg-type]
                })
            self._flow_orchestrator.subscribe(_flow_event_to_timeline)

            self._flow_skill_set = FlowSkillSet(
                orchestrator=self._flow_orchestrator,
                event_sink=None,  # injected later via set_flow_event_sink()
            )
            for skill in (
                RunFlowSkill(skill_set=self._flow_skill_set),
                FlowStatusSkill(skill_set=self._flow_skill_set),
                FlowWaitSkill(skill_set=self._flow_skill_set),
                FlowSkipSkill(skill_set=self._flow_skill_set),
            ):
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

    def peek_pending_finish(self) -> _PendingFinish | None:
        """供 presence dialogue 在 post_process 前读取本轮 Q/A。"""
        return self._pending_finish

    @staticmethod
    def _trunc(text: str, limit: int) -> str:
        return text[:limit] if limit > 0 and len(text) > limit else text

    @property
    def scheduler_engine(self):
        return self._scheduler_engine

    @property
    def timeline(self) -> TimelineService:
        return self._timeline

    @property
    def sub_event_sink(self):
        return self._sub_event_sink

    @sub_event_sink.setter
    def sub_event_sink(self, sink):
        self._sub_event_sink = sink
        if self._delegate_skill is not None:
            self._delegate_skill.sub_event_sink = sink

    def set_flow_event_sink(self, sink) -> None:
        """Inject an event_sink into the FlowSkillSet (called by WebUI after init)."""
        if self._flow_skill_set is not None:
            self._flow_skill_set.set_event_sink(sink)

    def set_plan_event_sink(self, sink) -> None:
        """Backward-compatible alias for set_flow_event_sink."""
        self.set_flow_event_sink(sink)

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
            medium_term=self._medium_term,
        )

        # medium_term 只需渲染一次，在整个问题的步骤循环中保持不变。
        _cached_medium: str = ""

        # Persona blocks are also stable across steps.
        # Load persisted LifeProfile once per TaoLoop session.
        if self._life is not None:
            self._life.load_profile()

        persona_blocks: list[PromptBlock] | None = None
        if self._soul is not None:
            from agent.adapters.soul_tao.persona_prompt import blocks_from_soul_query

            persona_blocks = blocks_from_soul_query(
                self._soul,
                max_profile_chars=self._cfg.persona.max_profile_chars,
            )
            if self._life is not None and not self._life.profile.is_empty():
                persona_blocks = persona_blocks + [LifeProfileBlock(self._life.profile)]
            if self._life is not None and not self._life.journal.is_empty():
                persona_blocks = persona_blocks + [JournalBlock(self._life.journal)]
        elif self._persona is not None:
            _blocks = self._persona.all_blocks()
            if self._life is not None and not self._life.profile.is_empty():
                _blocks = _blocks + [LifeProfileBlock(self._life.profile)]
            if self._life is not None and not self._life.journal.is_empty():
                _blocks = _blocks + [JournalBlock(self._life.journal)]
            persona_blocks = _blocks

        # Track the previous step's action for step-label logging.
        _prev_action: str = ""

        for i in range(self._cfg.max_steps):
            # ── Context assembly ─────────────────────────────────────────────
            # step 0：渲染 medium_term 并缓存；step > 0 直接复用。
            if i == 0:
                result = processor.recall()
                _cached_medium = result.medium_term
            else:
                result = MemoryResult(
                    short_term=processor.trace,
                    medium_term=_cached_medium,
                )

            # ── Message assembly ─────────────────────────────────────────────
            if self._static_cache is not None:
                messages = self._manager.build_messages_from_static(
                    self._static_cache,
                    question=question,
                    medium_term=result.medium_term,
                    short_term=result.short_term,
                )
            else:
                messages = self._manager.build_messages(
                    question,
                    result,
                    extra_system_blocks=persona_blocks,
                )

            # ── Active flow status injection ─────────────────────────────────
            if (
                self._flow_orchestrator is not None
                and self._flow_orchestrator.lifecycle_state.value
                    not in ("idle", "done", "failed", "aborted")
            ):
                from .action.skill.flow_skill import _format_flow_status
                flow_status_block = (
                    "\n\n【活跃 Flow 编排】\n"
                    + _format_flow_status(self._flow_orchestrator)
                )
                if messages and isinstance(messages[0], SystemMessage):
                    messages[0] = SystemMessage(
                        content=messages[0].content + flow_status_block
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

            # ── Step-label log ───────────────────────────────────────────────
            if i == 0:
                _step_label = "initial call"
            elif _prev_action:
                _step_label = f"prev={_prev_action}"
            else:
                _step_label = "continuation"
            logger.info("[Step %d] %s → LLM call", i, _step_label)

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
            #   L1   strict XML <T><A><O> / Output:[...] / Action:/Input: parsing (parser, free)
            #   L1b  lenient action inference within parser (free)
            #   LENIENT nudge — LENIENT quality appends a lightweight format hint to
            #        messages for the NEXT turn only; does NOT trigger a full L2 retry
            #        to avoid the cost of re-generating for every old-format response.
            #   L2   in-context correction retry (main LLM, 1 call per attempt)
            #   L3   isolated repair LLM (separate call, no conversation ctx)
            #   L4   explicit degradation → force finish with raw/output content
            tool_names = frozenset(self._executor.available_actions)
            result = parse_llm_output(raw_output, tool_names=tool_names)

            # LENIENT nudge: append a lightweight format reminder to messages
            # so the next turn gets a gentle nudge toward the XML format.
            # This is cheaper than a full L2 retry and avoids cost amplification
            # during the migration period when many models still use the old format.
            if result.quality == ParseQuality.LENIENT:
                _lenient_nudge = (
                    "[SYSTEM FORMAT REMINDER] Your previous response used the deprecated "
                    "Action:/Action Input: format. Please use XML tags in all future responses:\n"
                    "<T>reasoning</T>\n"
                    '<A>[{"action": "tool_name", "args": {...}}]</A>\n'
                    "<O>optional user-visible output</O>\n\n"
                    "[系统格式提示] 上一步使用了已弃用的 Action:/Action Input: 格式，"
                    "请在后续所有步骤使用 XML 标签格式：\n"
                    "<T>推理过程</T>\n"
                    '<A>[{"action": "工具名", "args": {...}}]</A>\n'
                    "<O>可选的用户可见输出</O>"
                )
                messages = messages + [
                    AIMessage(content=raw_output),
                    SystemMessage(content=_lenient_nudge),
                ]

            # _needs_retry: triggers full L2/L3 loop for truly broken outputs.
            # LENIENT is handled separately above with a cheaper nudge.
            def _needs_retry(r: "ParseResult") -> bool:  # type: ignore[name-defined]
                return (
                    r.quality == ParseQuality.FAILED and not r.is_finish
                ) or r.quality == ParseQuality.FINISH_DEGRADED

            # L2: in-context correction — inject a bilingual format reminder into
            # the existing conversation and retry the main LLM.  Runs first
            # because the model already has full context and self-correction is
            # cheapest before we resort to an isolated repair call.
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
                    if result.quality == ParseQuality.FINISH_DEGRADED:
                        _correction = (
                            "[SYSTEM FORMAT CORRECTION] Your <A> args are not valid JSON. "
                            "Since you want to finish, please rewrite using the XML format:\n"
                            "<T>your reasoning</T>\n"
                            '<A>[{"action": "finish", "args": {"answer": "your complete answer"}}]</A>\n'
                            "<O>your complete answer visible to the user</O>\n\n"
                            "[系统格式修正] <A> 的 args 不是合法 JSON。"
                            "请按以下 XML 格式重新输出 finish：\n"
                            "<T>推理过程</T>\n"
                            '<A>[{"action": "finish", "args": {"answer": "完整回答内容"}}]</A>\n'
                            "<O>在此填写给用户的完整回答</O>"
                        )
                    else:
                        _correction = (
                            "[SYSTEM FORMAT CORRECTION] Your output format is incorrect. "
                            "Please rewrite strictly using XML tags:\n"
                            "<T>your reasoning</T>\n"
                            '<A>[{"action": "tool_name", "args": {"key": "value"}}]</A>\n'
                            "<O>optional user-visible message</O>\n\n"
                            "For finishing:\n"
                            "<T>your reasoning</T>\n"
                            '<A>[{"action": "finish", "args": {"answer": "..."}}]</A>\n'
                            "<O>your complete answer</O>\n\n"
                            "[系统格式修正] 格式有误，请严格按照 XML 标签格式重新输出：\n"
                            "<T>推理过程</T>\n"
                            '<A>[{"action": "工具名", "args": {"key": "value"}}]</A>\n'
                            "<O>可选的用户可见输出</O>\n\n"
                            "结束时：\n"
                            "<T>推理过程</T>\n"
                            '<A>[{"action": "finish", "args": {"answer": "..."}}]</A>\n'
                            "<O>给用户的完整回答</O>"
                        )
                    correction_msgs = messages + [
                        AIMessage(content=raw_output),
                        SystemMessage(content=_correction),
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
            # accepting it.
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

            # L4: explicit degradation — all layers exhausted.
            # Force a finish using <O> content if present, otherwise raw_output.
            if _needs_retry(result):
                _l4_answer = result.output or result.action_input.get("answer") or raw_output
                _obs.emit(_ParseEvent(
                    session_id=_session_id,
                    ts=_time.time(),
                    step_index=i,
                    event_type="degraded_l4",
                    diagnosis="all escalation layers exhausted; forcing finish",
                ))
                result = ParseResult(
                    thought=result.thought,
                    action="finish",
                    action_input={"answer": _l4_answer},
                    raw=raw_output,
                    is_finish=True,
                    quality=ParseQuality.FAILED,
                    calls=None,
                    output=result.output,
                )

            if result.is_finish:
                # <O> is the primary user-visible answer; args.answer is fallback.
                answer = result.output or result.action_input.get("answer", raw_output)

                # Update prompt state synchronously before yielding so the
                # next turn can start immediately without waiting for the
                # background post_process to finish.  add_turn and build_static
                # are fast (~ms); _maybe_consolidate() has been moved to
                # post_process() to avoid blocking FinishEvent delivery.
                self._manager.add_turn(question, answer)
                self._static_cache = self._manager.build_static(
                    extra_system_blocks=persona_blocks,
                )

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
            # Resolve the calls list: prefer result.calls (new Output:[...] format);
            # fall back to a single-element list built from action/action_input.
            exec_calls: list[dict] = result.calls or [
                {"action": result.action, "args": result.action_input}
            ]

            _t_tool_start = _time.perf_counter()

            # ── Risk gate check — all calls pre-screened before any executes ──
            if self._risk_gate is not None and self._risk_gate.cfg.enabled:
                # Collect approval events for every high-risk call first.
                pending_approvals: list[tuple[dict, str, threading.Event]] = []
                for call in exec_calls:
                    risk = self._risk_gate.check(call["action"], call.get("args", {}))
                    if self._risk_gate.requires_approval(risk):
                        req_id = str(uuid.uuid4())
                        ev = threading.Event()
                        with self._approval_lock:
                            self._pending_approvals[req_id] = ev
                        timeout_secs = self._risk_gate.cfg.approval_timeout_secs
                        yield ApprovalRequestEvent(
                            request_id=req_id,
                            tool_name=call["action"],
                            args=call.get("args", {}),
                            risk_level=risk.level.value,
                            reason=risk.reason,
                            deadline_secs=timeout_secs,
                        )
                        pending_approvals.append((call, req_id, ev))

                # Wait for all approvals; if any is denied, abort the entire batch.
                denied_labels: list[str] = []
                for call, req_id, ev in pending_approvals:
                    timeout_secs = self._risk_gate.cfg.approval_timeout_secs
                    granted = ev.wait(timeout=timeout_secs)
                    with self._approval_lock:
                        self._pending_approvals.pop(req_id, None)
                        approved = self._approval_results.pop(req_id, False)
                    if not granted or not approved:
                        label = "超时未响应" if not granted else "用户拒绝"
                        denied_labels.append(f"[{label}] {call['action']!r}")

                if denied_labels:
                    observation = "操作未获批准，已取消执行：" + "、".join(denied_labels)
                    step = Step(
                        thought=result.thought,
                        action=result.action,
                        action_input=result.action_input,
                        observation=observation,
                        calls=exec_calls if result.calls else None,
                        output=result.output,
                    )
                    processor.add(step)
                    yield StepEvent(
                        index=i,
                        thought=result.thought,
                        action=result.action,
                        action_input=result.action_input,
                        observation=observation,
                        calls=exec_calls if result.calls else None,
                        output=result.output,
                    )
                    continue

            # ── Execute — parallel for multi-call, single for one call ────────
            if len(exec_calls) > 1:
                obs_list = self._executor.run_many(exec_calls)
                obs_list = [
                    self._trunc(o, self._cfg.prompt.max_observation_chars) for o in obs_list
                ]
                observation = "Observations:\n" + "\n".join(
                    f"[{c['action']}] → {o}" for c, o in zip(exec_calls, obs_list)
                )
            else:
                action_json = json.dumps(
                    {"action": exec_calls[0]["action"], "args": exec_calls[0].get("args", {})},
                    ensure_ascii=False,
                )
                observation = self._executor.run(action_json)
                observation = self._trunc(observation, self._cfg.prompt.max_observation_chars)

            _t_tool_end = _time.perf_counter()
            _obs.emit(_ToolCallEvent(
                session_id=_session_id,
                ts=_t_tool_start,
                step_index=i,
                tool_name=result.action,
                latency_ms=(_t_tool_end - _t_tool_start) * 1000,
                input_summary=json.dumps(exec_calls, ensure_ascii=False)[:200],
                output_summary=observation[:200],
            ))

            step = Step(
                thought=result.thought,
                action=result.action,
                action_input=result.action_input,
                observation=observation,
                calls=exec_calls if result.calls else None,
                output=result.output,
            )
            processor.add(step)
            _prev_action = result.action

            yield StepEvent(
                index=i,
                thought=result.thought,
                action=result.action,
                action_input=result.action_input,
                observation=observation,
                calls=exec_calls if result.calls else None,
                output=result.output,
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
        """Persist memory and evolve persona in the background.

        Prompt-state updates (add_turn / build_static) have already been done
        synchronously inside stream() before FinishEvent was yielded, so this
        method only handles heavy I/O that must not block the next turn.
        _maybe_consolidate() runs here (not in stream()) to avoid blocking
        FinishEvent delivery with embed+upsert latency spikes.
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

        # Persona 自动演化已断开；轮末不再调用 PersonaService.evolution.record_turn。

    # ── Misc ─────────────────────────────────────────────────────────────────

    def preload(self) -> None:
        """旧接口保留，现为空操作。长期记忆不再在会话启动时预热。"""

    def preload_with_recall(self) -> None:
        """旧接口保留，现为空操作。长期记忆通过 soul_memory_search 工具主动触发。"""

    def close(self) -> None:
        if self._soul is not None:
            self._soul.stop()

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

        medium_dir = self._cfg.memory.medium_term.memory_dir

        targets = [
            os.path.join(medium_dir, "medium_term.jsonl"),
        ]
        for fpath in targets:
            if fpath and os.path.exists(fpath):
                os.remove(fpath)

        if self._medium_term is not None:
            self._medium_term._entries.clear()

    def clear_persona(self) -> None:
        """清空 self_concept、体验 buffer 与 Presence.affect（管理操作，非漂移）。"""
        if self._soul is not None:
            self._soul.persona.service.reset_self_concept()
            self._soul.reset_presence_affect()
            return
        if self._persona is None:
            raise RuntimeError("Persona not enabled.")
        self._persona.reset_self_concept()

    def run(self, question: str) -> str:
        from agent.adapters.soul_dialogue import commit_turn_and_post_process

        for event in self.stream(question):
            if isinstance(event, FinishEvent):
                commit_turn_and_post_process(
                    soul=self._soul,
                    tao=self,
                    session_id="tao",
                )
                return event.answer
            if isinstance(event, MaxStepsEvent):
                raise RuntimeError(
                    f"TaoLoop exceeded max_steps={event.max_steps} without finishing"
                )
        raise RuntimeError(f"TaoLoop exhausted stream without FinishEvent")
