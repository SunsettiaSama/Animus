from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .compose.bundle import SpeakPromptBundle, SpeakTurnMode
from .compose.composer import SpeakPromptComposer
from .compose.context import SpeakContextDistiller
from .compose.runner import SpeakComposeRunner
from .compose.reply_style import SpeakReplyStyle
from .compose.recall import perform_recall_handoff
from .drive import SpeakDriveBridge, SpeakDriveResult, SpeakDriveSnapshot
from .io.inbound import SpeakDialogueBridge, SpeakIngestResult, SpeakInboundPort, ingest_question
from .io.inbound.compose.gateway import InboundComposeGateway
from .io.inbound.compose.request import ComposePrepareRequest
from .io.inbound.memory import InboundMemoryGateway, RecallRequest, RecallResult
from .io.inbound.session.bridge import SpeakSessionBridge
from .session import SpeakSessionManager, SpeakSessionService
from .session.queue import QueueDecisionRunner, UserInputItem
from .session.turn import SessionTurnHost, run_session_turn
from .session import SpeakFeelingChunk, SpeakSubjectiveChunk, SpeakTurnChunk
from .session.lifecycle import SPEAK_SESSION_IDLE_SEC, SpeakSessionRegistry
from .session.lifecycle import (
    CompositeSemanticBoundary,
    EmbeddingSemanticBoundary,
    SemanticSessionBoundary,
    TopicShiftSemanticBoundary,
)
from .io.inbound.unit import SpeakExchange
from .io.outbound import SpeakDeliverResult, SpeakOutboundPort, SpeakRequest, deliver_text
from .io.outbound.unit import SpeakAnswer
from .llm.engine import SpeakLLMEngine, SpeakLLMResult
from .io.outbound.stream import (
    SpeakAgentOutput,
    SpeakStreamChannel,
    SpeakStreamEvent,
    SpeakStreamPipeline,
    SpeakStreamPort,
    parse_agent_output,
)
from .io.outbound.stream.flush import SpeakFlushMode
from .ports import SpeakDrivePort, SpeakToolPort

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService, PresenceSnapshot
    from .io.outbound import SpeakRequest

logger = logging.getLogger(__name__)


@dataclass
class SpeakTurnResult:
    """一轮 speak 编排结果。"""

    session_id: str
    answer: str
    bundle: SpeakPromptBundle
    output: SpeakAgentOutput | None = None
    stream_events: list[SpeakStreamEvent] = field(default_factory=list)
    recorded: bool = False
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class SpeakService(SpeakInboundPort, SpeakOutboundPort, SpeakDrivePort):
    """Soul 对话编排：字块组装 → LLM → 流式推送 → 记账。"""

    def __init__(
        self,
        *,
        presence: PresenceService | None = None,
        persona=None,
        inbound: SpeakInboundPort | None = None,
        outbound: SpeakOutboundPort | None = None,
        record_turn: Callable[..., None] | None = None,
        dialogue_bridge: SpeakDialogueBridge | None = None,
        llm_engine: SpeakLLMEngine | None = None,
        composer: SpeakPromptComposer | None = None,
        stream_pipeline: SpeakStreamPipeline | None = None,
        session_registry: SpeakSessionRegistry | None = None,
        semantic_boundary: SemanticSessionBoundary | None = None,
        embedder=None,
        semantic_distance_threshold: float = 0.42,
        tool_port: SpeakToolPort | None = None,
        reply_style: SpeakReplyStyle | None = None,
        flush_mode: SpeakFlushMode = "segment",
        share_threshold: float | None = None,
        session_idle_sec: float | None = None,
        lifecycle=None,
        touch_dialogue: Callable[[str], None] | None = None,
        context_distiller: SpeakContextDistiller | None = None,
        context_distill_chunk_size: int = 4,
    ) -> None:
        self._presence = presence
        self._persona = persona
        self._compose_runner = SpeakComposeRunner()
        self._inbound_compose = InboundComposeGateway(self._compose_runner)
        self._inbound_memory = InboundMemoryGateway()
        self._inbound = inbound
        self._outbound = outbound
        self._reply_style = reply_style or SpeakReplyStyle()
        self._llm = llm_engine or SpeakLLMEngine()
        self._queue_decision_runner = QueueDecisionRunner(llm=self._llm)
        self._tool = tool_port
        self._drive = SpeakDriveBridge(presence, share_threshold=share_threshold)
        on_dialogue = record_turn
        self._dialogue_bridge = dialogue_bridge or SpeakDialogueBridge(
            on_dialogue_turn=on_dialogue,
        )
        if context_distiller is not None:
            self._context = context_distiller
        elif llm_engine is not None:
            self._context = SpeakContextDistiller(
                llm_engine=llm_engine,
                chunk_size=context_distill_chunk_size,
            )
        else:
            self._context = None
        if composer is not None:
            self._composer = composer
        elif persona is not None and presence is not None:
            self._composer = SpeakPromptComposer(
                persona,
                presence,
                share_threshold=share_threshold or self._drive.share_threshold,
                context_distiller=self._context,
                status_store=self._inbound_compose.status_store,
            )
        else:
            self._composer = None
        self._semantic = semantic_boundary or self._build_semantic_boundary(
            embedder,
            semantic_distance_threshold,
        )
        idle = session_idle_sec if session_idle_sec is not None else SPEAK_SESSION_IDLE_SEC
        self._session_manager = SpeakSessionManager(
            presence=presence,
            semantic=self._semantic,
            idle_sec=idle,
            inner_lifecycle=lifecycle,
            touch_dialogue=touch_dialogue,
            registry=session_registry,
            reset_context=self.reset_context,
        )
        self._session_manager.bind_record_fn(self.record_turn)
        self._session_manager.bind_compose_scheduler(
            lambda session_id, mode: self._schedule_compose_prepare(session_id, mode=mode),
        )
        self._session_manager.bind_queue_decision_scheduler(self._schedule_queue_decision)
        self._queue_decision_runner.set_complete_handler(
            self._session_manager.on_queue_decision_complete,
        )
        self._session_bridge = SpeakSessionBridge(self, manager=self._session_manager)
        self._inbound_compose.attach_scheduler(self._on_compose_prepare_request)
        self._outbound_stream = SpeakStreamChannel()
        self._stream = stream_pipeline or SpeakStreamPipeline(
            flush_mode=flush_mode,
            emit_fn=self._outbound_stream.emit,
        )
        self._compose_runner.set_frame_ready_handler(
            lambda frame, mode: self._session_manager.on_compose_ready(frame, mode=mode),
        )

    @staticmethod
    def _build_semantic_boundary(embedder, threshold: float) -> SemanticSessionBoundary:
        explicit = TopicShiftSemanticBoundary()
        if embedder is None:
            return explicit
        return CompositeSemanticBoundary(
            explicit=explicit,
            embedding=EmbeddingSemanticBoundary(
                embedder,
                distance_threshold=threshold,
            ),
        )

    @property
    def llm_engine(self) -> SpeakLLMEngine:
        return self._llm

    @property
    def composer(self) -> SpeakPromptComposer | None:
        return self._composer

    @property
    def compose_runner(self) -> SpeakComposeRunner:
        return self._compose_runner

    @property
    def queue_decision_runner(self) -> QueueDecisionRunner:
        return self._queue_decision_runner

    def start(self) -> None:
        self._compose_runner.start()
        self._queue_decision_runner.start()
        self._schedule_compose_prepare("tao")

    def stop(self) -> None:
        self._queue_decision_runner.stop()
        self._compose_runner.stop()

    @property
    def stream_pipeline(self) -> SpeakStreamPipeline:
        return self._stream

    @property
    def outbound_stream(self) -> SpeakStreamChannel:
        return self._outbound_stream

    @property
    def session_registry(self) -> SpeakSessionRegistry:
        return self._session_bridge.registry

    @property
    def inbound_compose(self) -> InboundComposeGateway:
        return self._inbound_compose

    @property
    def inbound_memory(self) -> InboundMemoryGateway:
        return self._inbound_memory

    @property
    def session_manager(self) -> SpeakSessionService:
        return self._session_manager

    @property
    def session_bridge(self) -> SpeakSessionBridge:
        return self._session_bridge

    @property
    def drive_bridge(self) -> SpeakDriveBridge:
        return self._drive

    @property
    def dialogue_bridge(self) -> SpeakDialogueBridge:
        return self._dialogue_bridge

    @property
    def context_distiller(self) -> SpeakContextDistiller | None:
        return self._context

    def reset_context(self, session_id: str) -> None:
        self._inbound_compose.reset_session(session_id)
        self._session_manager.clear_compose(session_id)
        if self._context is not None:
            self._context.reset_session(session_id)

    def attach_memory_recall(self, recall_fn) -> None:
        self._inbound_memory.attach_recall(recall_fn)

    def _on_compose_prepare_request(self, request: ComposePrepareRequest) -> None:
        if self._composer is None:
            return
        self._compose_runner.schedule_prepare(
            self._composer,
            request.session_id,
            mode=request.mode,
            reply_style=self._reply_style,
        )

    def _schedule_compose_prepare(
        self,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> None:
        self._inbound_compose.request_prepare(
            ComposePrepareRequest(session_id=session_id, mode=mode),
        )

    def _schedule_queue_decision(
        self,
        session_id: str,
        ctx,
        token: int,
    ) -> None:
        from .session.queue import InterruptContext

        if not isinstance(ctx, InterruptContext):
            return
        if self._context is not None:
            ctx.dialogue_compressed = self._context.prompt_block(session_id)
        self._queue_decision_runner.schedule(
            session_id,
            ctx,
            token,
            llm=self._llm,
        )

    def on_presence_status_update(self, snap: PresenceSnapshot) -> None:
        """接收 presence 推送，由 inbound compose 写入状态并请求预组装。"""
        self._inbound_compose.on_presence_status_update(snap)

    def set_stream_port(self, port: SpeakStreamPort | None) -> None:
        self._outbound_stream.bind(port)

    def set_tool_port(self, port: SpeakToolPort | None) -> None:
        self._tool = port

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange:
        return self.ingest_question(session_id, text).exchange

    def ingest_question(self, session_id: str, text: str) -> SpeakIngestResult:
        return ingest_question(session_id, text)

    def deliver(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakAnswer:
        return self.speak(session_id, text, final=final).answer

    def speak(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakDeliverResult:
        return deliver_text(session_id, text, final=final)

    def generate(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        self._session_manager.open(session_id)
        return self._llm.generate(user_text, system=system, context=context)

    def generate_stream(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        self._session_manager.open(session_id)
        return self._llm.generate_stream(user_text, system=system, context=context)

    def _compose_bundle(
        self,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> SpeakPromptBundle:
        if self._composer is None:
            from .compose.injected import SpeakInjectedContext
            from agent.soul.speak.io.inbound.compose import SpeakStatusInjected
            from agent.soul.presence.share_desire import ShareDesire
            from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage

            from .compose.share import ShareComposeState
            from .compose.system import build_system_prompt

            dialogue_compressed = ""
            if self._context is not None:
                dialogue_compressed = self._context.prompt_block(session_id)

            presence_snap = self._presence.snapshot(session_id) if self._presence is not None else None
            status = self._inbound_compose.collect_status(
                presence_snap,
                dialogue_compressed=dialogue_compressed,
            ) if presence_snap is not None else SpeakStatusInjected(
                dialogue_compressed=dialogue_compressed,
            )

            empty_share = ShareComposeState(
                wants_share=False,
                summary="",
                events=(),
                package=ShareFoldedPackage(
                    summary="",
                    entries=(),
                    peak_salience=0.0,
                    total_salience=0.0,
                    peak_share_desire=ShareDesire.none,
                    count=0,
                ),
            )

            return SpeakPromptBundle(
                session_id=session_id,
                mode=mode,
                injected=SpeakInjectedContext(
                    user_text=user_text.strip(),
                    status=status,
                ),
                system=build_system_prompt(
                    mode=mode,
                    share_state=empty_share,
                    output_format=self._reply_style.render_prompt(),
                ),
                reply_style=self._reply_style,
            )

        queued = self._session_manager.pop_compose(session_id, mode=mode)
        if queued is not None:
            bundle = self._composer.finalize(queued.frame, user_text)
            bundle.meta["compose_source"] = "session_queue"
            return bundle

        frame = self._compose_runner.take_ready_frame(session_id, mode=mode)
        if frame is not None:
            return self._composer.finalize(frame, user_text)

        bundle = self._composer.compose(
            session_id,
            user_text,
            mode=mode,
            reply_style=self._reply_style,
        )
        bundle.meta["compose_source"] = "sync_fallback"
        return bundle

    _SHARE_HANDOFF_INSTRUCTION = (
        "请基于以上分享详情，向用户自然分享；输出仍需包含 think 与 state:finish（或 append）。"
    )
    _RECALL_HANDOFF_INSTRUCTION = (
        "请基于以上回忆检索结果自然回复用户；输出仍需包含 think 与 state:finish（或 append）。"
    )

    def _compose_from_queue(
        self,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> SpeakPromptBundle | None:
        if self._composer is None:
            return None
        queued = self._session_manager.pop_compose(session_id, mode=mode)
        if queued is None:
            return None
        bundle = self._composer.finalize(queued.frame, user_text)
        bundle.meta["compose_source"] = "session_queue"
        return bundle

    def _generate_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
    ) -> tuple[str, list[SpeakStreamEvent]]:
        self._outbound_stream.begin_session(session_id)
        if stream:
            events = list(
                self._stream.stream_generate(
                    self._llm,
                    session_id,
                    user_text,
                    system=system,
                    context="",
                )
            )
            answer = next(
                (event.text for event in reversed(events) if event.kind == "finish"),
                "",
            )
            return answer, events

        llm_result = self._llm.generate(
            user_text,
            system=system,
        )
        answer = llm_result.text
        events = list(self._stream.emit_parsed_output(session_id, answer))
        return answer, events

    def _continue_share_handoff(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
        notes: list[str],
    ) -> tuple[str, list[SpeakStreamEvent], SpeakAgentOutput] | None:
        if self._presence is None or self._composer is None:
            notes.append("share handoff: no presence/composer")
            return None

        handoff = self._composer.share.pop_handoff(self._presence, session_id)
        if not handoff.ok:
            notes.append(f"share handoff: {handoff.reason}")
            return None

        topic = handoff.event.topic if handoff.event is not None else "pop"
        notes.append(f"share handoff: {topic}")
        handoff_system = (
            f"{system}\n\n{handoff.full_text}\n\n{self._SHARE_HANDOFF_INSTRUCTION}"
        )
        answer, events = self._generate_turn(
            session_id,
            user_text,
            system=handoff_system,
            stream=stream,
        )
        parsed = parse_agent_output(answer)
        return answer, events, parsed

    def _continue_recall_handoff(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
        notes: list[str],
        parsed: SpeakAgentOutput,
    ) -> tuple[str, list[SpeakStreamEvent], SpeakAgentOutput] | None:
        query = parsed.recall_query.strip()
        if not query:
            notes.append("recall handoff: empty query")
            return None

        handoff = perform_recall_handoff(
            self._inbound_memory,
            session_id=session_id,
            query=query,
        )
        if not handoff.ok:
            notes.append(f"recall handoff: {handoff.reason}")
            return None

        notes.append(f"recall handoff: {handoff.query}")
        handoff_system = (
            f"{system}\n\n{handoff.full_text}\n\n{self._RECALL_HANDOFF_INSTRUCTION}"
        )
        answer, events = self._generate_turn(
            session_id,
            user_text,
            system=handoff_system,
            stream=stream,
        )
        parsed = parse_agent_output(answer)
        return answer, events, parsed

    def run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: SpeakTurnMode = "inbound",
        record: bool = True,
    ) -> SpeakTurnResult:
        submit = self._session_manager.submit_user_input(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            record=record,
        )
        if submit.queued:
            return SpeakTurnResult(
                session_id=session_id,
                answer="",
                bundle=SpeakPromptBundle(session_id=session_id, mode=mode),
                recorded=False,
                notes=list(submit.notes),
                meta={
                    "queued": True,
                    "interrupt": submit.interrupt,
                    "session_state": "queued",
                },
            )

        initial = UserInputItem(
            session_id=session_id,
            user_text=user_text.strip(),
            mode=mode,
            stream=stream,
            record=record,
        )
        result = self._process_user_inputs(session_id, initial=initial)
        logger.debug("speak prompt bundle: %s", result.bundle.summary_for_log())
        return result

    def _process_user_inputs(
        self,
        session_id: str,
        *,
        initial: UserInputItem | None = None,
    ) -> SpeakTurnResult:
        result: SpeakTurnResult | None = None
        if initial is not None:
            result = self._run_one_user_turn(initial)

        while True:
            pending = self._session_manager.pop_pending_user_input(session_id)
            if pending is None:
                break
            result = self._run_one_user_turn(pending)

        if result is None:
            raise RuntimeError("speak: no user input to process")
        return result

    def _run_one_user_turn(self, item: UserInputItem) -> SpeakTurnResult:
        if item.interrupted:
            interrupt_context = self._session_manager.prepare_interrupt_turn(
                item.session_id,
                item,
            )
        else:
            interrupt_context = None
        host = SessionTurnHost(
            compose_bundle=self._compose_bundle,
            llm=self._llm,
            stream_pipeline=self._stream,
            outbound_stream=self._outbound_stream,
            record_turn=self.record_turn,
            schedule_compose=lambda sid: self._schedule_compose_prepare(sid, mode=item.mode),
            continue_share_handoff=self._continue_share_handoff,
            continue_recall_handoff=self._continue_recall_handoff,
            compose_from_queue=self._compose_from_queue,
            parse_agent_output=parse_agent_output,
        )
        result = run_session_turn(
            self._session_manager,
            host,
            item.session_id,
            item.user_text,
            stream=item.stream,
            mode=item.mode,
            record=item.record,
            interrupt_context=interrupt_context,
        )
        if item.interrupted and interrupt_context is not None:
            if interrupt_context.queue_decision_maintain is True:
                result.notes.append("queue_decision: maintain")
            elif interrupt_context.queue_decision_maintain is False:
                result.notes.append("queue_decision: drop")
            if interrupt_context.queue_decision_reorder is not None:
                order = ",".join(str(i) for i in interrupt_context.queue_decision_reorder)
                result.notes.append(f"queue_decision: reorder {order}")
            result.meta["queue_decision_maintain"] = interrupt_context.queue_decision_maintain
        return result

    def handle_proactive(
        self,
        request: SpeakRequest,
        *,
        gate_fn: Callable[..., dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if gate_fn is not None:
            return gate_fn(request)
        message = request.reason.strip() or request.package.summary.strip()
        if not message:
            return {"ok": False, "reason": "empty proactive message"}
        share_line = request.package.summary.strip()
        narration_parts = [
            part for part in (request.presence_narrative.strip(), share_line) if part
        ]
        narration = "\n".join(narration_parts)
        return self.deliver_agent_message(
            session_id=request.session_id,
            message=message,
            narration=narration,
        )

    def run_semantic_fallback(
        self,
        instruction: str,
        *,
        session_id: str = "tao",
    ) -> dict[str, Any]:
        if self._tool is None:
            raise RuntimeError("SpeakToolPort 未配置")
        return self._tool.run_semantic_task(instruction, session_id=session_id)

    def record_turn(
        self,
        chunk: SpeakTurnChunk,
    ) -> SpeakIngestResult:
        exchange = self._dialogue_bridge.record_turn(chunk)
        if self._context is not None:
            self._context.on_turn(
                chunk.session_id,
                chunk.user_text,
                chunk.agent_text,
            )
        return SpeakIngestResult(
            exchange=exchange,
            notes=["penetrated: presence/experience"],
        )

    def record_dialogue(
        self,
        session_id: str,
        user_text: str,
        agent_text: str,
        *,
        subjective: SpeakSubjectiveChunk | None = None,
        feeling: SpeakFeelingChunk | None = None,
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> SpeakIngestResult:
        chunk = SpeakTurnChunk(
            session_id=session_id,
            user_text=user_text,
            agent_text=agent_text,
            subjective=subjective or SpeakSubjectiveChunk(),
            feeling=feeling or SpeakFeelingChunk(),
            activated_memory_ids=list(activated_memory_ids or []),
            proactive_intent_id=proactive_intent_id,
        )
        return self.record_turn(chunk)

    def deliver_agent_message(
        self,
        *,
        session_id: str,
        message: str,
        user_text: str = "",
        narration: str = "",
        proactive_intent_id: str = "",
        record: bool = True,
    ) -> dict[str, Any]:
        text = message.strip()
        if not text:
            raise ValueError("speak message 不能为空")
        self._session_manager.open(
            session_id,
            trigger="proactive_outbound",
            proactive_message=text,
            proactive_intent_id=proactive_intent_id,
        )
        turn = None
        if record:
            chunk = SpeakTurnChunk(
                session_id=session_id,
                user_text=user_text,
                agent_text=text,
                subjective=SpeakSubjectiveChunk(narration=narration),
                proactive_intent_id=proactive_intent_id,
            )
            dispatch = self._session_manager.record_turn(
                chunk,
                on_after=lambda sid: self._schedule_compose_prepare(sid),
            )
            turn = dispatch
        return {
            "ok": True,
            "session_id": session_id,
            "message": text,
            "exchange_id": turn.exchange_id if turn is not None else "",
        }

    def drive_snapshot(self, session_id: str) -> SpeakDriveSnapshot:
        return self._drive.snapshot(session_id)

    def evaluate_drive(self, session_id: str) -> SpeakDriveResult:
        return self._drive.evaluate(session_id)

    def tick_intrinsic_drive(self, session_id: str) -> SpeakDriveResult:
        return self.evaluate_drive(session_id)

    def iter_stream_events(
        self,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> Iterator[SpeakStreamEvent]:
        self._session_manager.open(session_id)
        bundle = self._compose_bundle(session_id, user_text, mode=mode)
        system = bundle.build_system()
        yield from self._stream.stream_generate(
            self._llm,
            session_id,
            bundle.user_text or user_text,
            system=system,
        )
