from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .bridge import SpeakDialogueBridge
from .chunk import SpeakFeelingChunk, SpeakSubjectiveChunk, SpeakTurnChunk
from .compose.bundle import SpeakPromptBundle, SpeakTurnMode
from .compose.composer import SpeakPromptComposer
from .compose.reply_style import SpeakReplyStyle
from .drive import SpeakDriveBridge, SpeakDriveResult, SpeakDriveSnapshot
from .llm.engine import SpeakLLMEngine, SpeakLLMResult
from .parse.parser import parse_agent_output
from .parse.model import SpeakAgentOutput
from .tools.anchor import build_anchor_request
from .ports import SpeakDrivePort, SpeakInboundPort, SpeakOutboundPort, SpeakStreamPort, SpeakToolPort
from .session.registry import SPEAK_SESSION_IDLE_SEC, SpeakSessionRegistry
from .session.semantic import SemanticSessionBoundary, TopicShiftSemanticBoundary
from .stream.events import SpeakStreamEvent
from .stream.pipeline import SpeakFlushMode, SpeakStreamPipeline
from .unit import SpeakAnswer, SpeakExchange, SpeakQuestion

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService
    from .outbound import SpeakRequest

logger = logging.getLogger(__name__)


@dataclass
class SpeakIngestResult:
    """用户话语摄入结果。"""

    exchange: SpeakExchange
    notes: list[str] = field(default_factory=list)


@dataclass
class SpeakDeliverResult:
    """对外说话交付结果。"""

    answer: SpeakAnswer
    notes: list[str] = field(default_factory=list)


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
        tool_port: SpeakToolPort | None = None,
        reply_style: SpeakReplyStyle | None = None,
        flush_mode: SpeakFlushMode = "segment",
        share_threshold: float | None = None,
        session_idle_sec: float | None = None,
        lifecycle=None,
        touch_dialogue: Callable[[str], None] | None = None,
    ) -> None:
        self._presence = presence
        self._persona = persona
        self._inbound = inbound
        self._outbound = outbound
        self._reply_style = reply_style or SpeakReplyStyle()
        self._llm = llm_engine or SpeakLLMEngine()
        self._tool = tool_port
        self._drive = SpeakDriveBridge(presence, share_threshold=share_threshold)
        on_dialogue = record_turn
        self._dialogue_bridge = dialogue_bridge or SpeakDialogueBridge(
            on_dialogue_turn=on_dialogue,
        )
        if composer is not None:
            self._composer = composer
        elif persona is not None and presence is not None:
            self._composer = SpeakPromptComposer(
                persona,
                presence,
                share_threshold=share_threshold or self._drive.share_threshold,
            )
        else:
            self._composer = None
        self._semantic = semantic_boundary or TopicShiftSemanticBoundary()
        idle = session_idle_sec if session_idle_sec is not None else SPEAK_SESSION_IDLE_SEC
        self._sessions = session_registry or SpeakSessionRegistry(
            idle_sec=idle,
            lifecycle=lifecycle,
            touch_dialogue=touch_dialogue,
        )
        self._stream = stream_pipeline or SpeakStreamPipeline(
            flush_mode=flush_mode,
            reply_style=self._reply_style,
        )

    @property
    def llm_engine(self) -> SpeakLLMEngine:
        return self._llm

    @property
    def composer(self) -> SpeakPromptComposer | None:
        return self._composer

    @property
    def stream_pipeline(self) -> SpeakStreamPipeline:
        return self._stream

    @property
    def session_registry(self) -> SpeakSessionRegistry:
        return self._sessions

    @property
    def drive_bridge(self) -> SpeakDriveBridge:
        return self._drive

    @property
    def dialogue_bridge(self) -> SpeakDialogueBridge:
        return self._dialogue_bridge

    def set_stream_port(self, port: SpeakStreamPort | None) -> None:
        self._stream.stream_port = port

    def set_tool_port(self, port: SpeakToolPort | None) -> None:
        self._tool = port

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange:
        return self.ingest_question(session_id, text).exchange

    def ingest_question(self, session_id: str, text: str) -> SpeakIngestResult:
        exchange = SpeakExchange(
            session_id=session_id,
            question=SpeakQuestion(text=text),
        )
        return SpeakIngestResult(exchange=exchange)

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
        answer = SpeakAnswer(text=text, final=final)
        return SpeakDeliverResult(answer=answer)

    def generate(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        self._sessions.ensure_active(session_id)
        return self._llm.generate(user_text, system=system, context=context)

    def generate_stream(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> SpeakLLMResult:
        self._sessions.ensure_active(session_id)
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
            from .compose.share_queue import SharePromptHint
            from .compose.system import build_system_prompt

            return SpeakPromptBundle(
                session_id=session_id,
                mode=mode,
                injected=SpeakInjectedContext(user_text=user_text.strip()),
                system=build_system_prompt(
                    mode=mode,
                    share_hint=SharePromptHint(),
                    output_format=self._reply_style.render_prompt(),
                ),
                reply_style=self._reply_style,
            )
        return self._composer.compose(
            session_id,
            user_text,
            mode=mode,
            reply_style=self._reply_style,
        )

    def run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: SpeakTurnMode = "inbound",
        record: bool = True,
    ) -> SpeakTurnResult:
        self._sessions.ensure_active(session_id)
        bundle = self._compose_bundle(session_id, user_text, mode=mode)
        logger.debug("speak prompt bundle: %s", bundle.summary_for_log())

        system = bundle.build_system()
        if stream:
            events = list(
                self._stream.stream_generate(
                    self._llm,
                    session_id,
                    bundle.user_text or user_text,
                    system=system,
                    context="",
                )
            )
            answer = next(
                (event.text for event in reversed(events) if event.kind == "finish"),
                "",
            )
        else:
            llm_result = self._llm.generate(
                bundle.user_text or user_text,
                system=system,
            )
            answer = llm_result.text
            events = list(self._stream.emit_parsed_output(session_id, answer))

        parsed = parse_agent_output(answer)
        answer_body = parsed.speak or answer.strip()

        notes: list[str] = []
        if parsed.anchor_tool:
            notes.append(f"anchor: {parsed.anchor_tool}")
        if parsed.session_state == "append":
            notes.append("session_state: append")
        recorded = False
        if record and answer_body:
            chunk = SpeakTurnChunk(
                session_id=session_id,
                user_text=user_text,
                agent_text=answer_body,
                subjective=SpeakSubjectiveChunk(prior_thought=parsed.thought),
            )
            if self._semantic.should_rotate(session_id, last_turn=chunk):
                reason = self._semantic.reason()
                notes.append(f"semantic rotate: {reason}")
                if self._sessions._lifecycle is not None:
                    self._sessions._lifecycle.close_dialogue_interaction(session_id)
                    self._sessions._lifecycle.start_dialogue_session(session_id)
            self.record_turn(chunk)
            recorded = True
            self._sessions.touch(session_id)

        anchor_request = (
            build_anchor_request(parsed.anchor_tool)
            if parsed.anchor_tool
            else None
        )

        return SpeakTurnResult(
            session_id=session_id,
            answer=answer_body,
            bundle=bundle,
            output=parsed,
            stream_events=events,
            recorded=recorded,
            notes=notes,
            meta={
                "session_state": parsed.session_state,
                "anchor_request": anchor_request,
            },
        )

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
        self._sessions.ensure_active(session_id)
        if record:
            turn = self.record_dialogue(
                session_id,
                user_text,
                text,
                subjective=SpeakSubjectiveChunk(narration=narration),
                proactive_intent_id=proactive_intent_id,
            )
            self._sessions.touch(session_id)
        else:
            turn = None
        return {
            "ok": True,
            "session_id": session_id,
            "message": text,
            "exchange_id": turn.exchange.id if turn is not None else "",
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
        bundle = self._compose_bundle(session_id, user_text, mode=mode)
        system = bundle.build_system()
        yield from self._stream.stream_generate(
            self._llm,
            session_id,
            bundle.user_text or user_text,
            system=system,
        )
