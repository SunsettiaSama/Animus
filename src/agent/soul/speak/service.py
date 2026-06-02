from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.inbound.memory.recall import perform_recall_handoff

from .orchestrator import (
    ShareDesireComposer,
    SpeakContextDistiller,
    SpeakOrchestrator,
    SpeakPromptBundle,
    SpeakReplyStyle,
    SpeakTurnMode,
)
from .orchestrator.guidance.control import GuidanceControlService
from .orchestrator.io import OrchestratorIOHub
from .orchestrator.runner import SpeakComposeRunner
from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD
from .io.hub import SpeakIOHub
from .io.inbound import SpeakDialogueBridge, SpeakIngestResult, SpeakInboundPort, ingest_question
from .io.inbound.compose.gateway import InboundComposeGateway
from .io.inbound.compose.request import ComposePrepareRequest
from .io.inbound.drive import SpeakDriveBridge, SpeakDriveResult, SpeakDriveSnapshot
from .io.inbound.memory import InboundMemoryGateway, SimilarMemoryPullResult
from .session import SpeakSessionManager, SpeakSessionService
from .session.queue import QueueDecisionRunner, UserInputItem
from .session.manage import SilenceBreakTurnSpec
from .orchestrator.prompt_trace import get_prompt_trace
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
from .io.outbound.hub import SpeakOutboundHub
from .io.outbound.life import SpeakLifeLifecycleBridge, SpeakLifeOutboundBridge
from .io.outbound.stream_hub import SpeakOutboundStreamHub
from .io.inbound.hub import SpeakInboundHub
from .io.outbound.stream.flush import SpeakFlushMode, SpeakTypingHoldEmitter
from .orchestrator.turn_coordinator import OrchestratorTurnCoordinator
from .llm.director_engine import SpeakDirectorLLMEngine
from .session.director import (
    BrewDispatcher,
    DirectorInput,
    DirectorWorker,
    SessionDialogueDirector,
)
from .ports import SpeakDrivePort, SpeakToolPort
from agent.soul.workers import DomainWorker

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
    """Soul 对话编排：字块组装 → LLM → 流式推送 → 记账。

    出入站经 ``self.io``（``SpeakIOHub``）；会话真逻辑在 ``session_manager`` / ``session_registry``。
    不使用 ``agent.interaction.DialogueKernel`` / ``agent.posture``。
    Life 体验注入经 ``io.outbound.life`` → ``life.io.speak``。
    """

    def __init__(
        self,
        *,
        presence: PresenceService | None = None,
        persona=None,
        inbound: SpeakInboundPort | None = None,
        outbound: SpeakOutboundPort | None = None,
        life_outbound: SpeakLifeOutboundBridge | None = None,
        dialogue_bridge: SpeakDialogueBridge | None = None,
        llm_engine: SpeakLLMEngine | None = None,
        orchestrator: SpeakOrchestrator | None = None,
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
        life_lifecycle: SpeakLifeLifecycleBridge | None = None,
        context_distiller: SpeakContextDistiller | None = None,
        context_distill_chunk_size: int = 4,
        memory_turn_gap: int = 3,
        keyword_wait_ms: int = 200,
        memory_budget: int = 5,
        portrait_wait_ms: int = 100,
        story_port=None,
        world_id_fn: Callable[[], str] | None = None,
        director_llm_engine: SpeakDirectorLLMEngine | None = None,
        director_push_now_cooldown_sec: float = 8.0,
        director_brew_queue_max: int = 3,
        typing_idle_ms: int = 3000,
    ) -> None:
        self._presence = presence
        self._persona = persona
        self._story_port = story_port
        self._world_id_fn = world_id_fn
        self._compose_runner = SpeakComposeRunner()
        self._memory_turn_gap = memory_turn_gap
        self._portrait_wait_ms = max(0, portrait_wait_ms)
        self._llm = llm_engine or SpeakLLMEngine()
        self._guidance_control = GuidanceControlService(llm=self._llm)
        self._guidance_io = OrchestratorIOHub.from_control_service(self._guidance_control)
        self._inbound = inbound
        self._outbound = outbound
        self._reply_style = reply_style or SpeakReplyStyle()
        self._queue_decision_runner = QueueDecisionRunner(llm=self._llm)
        self._tool = tool_port
        self._life_outbound = life_outbound
        if dialogue_bridge is not None:
            self._dialogue_bridge = dialogue_bridge
        elif life_outbound is not None:
            self._dialogue_bridge = SpeakDialogueBridge(life=life_outbound)
        else:
            raise RuntimeError("SpeakService 需要 life_outbound 或 dialogue_bridge")
        session_lifecycle = life_lifecycle if life_lifecycle is not None else lifecycle
        touch_dialogue = (
            life_outbound.touch_dialogue
            if life_outbound is not None
            else None
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
        self._semantic = semantic_boundary or self._build_semantic_boundary(
            embedder,
            semantic_distance_threshold,
        )
        idle = session_idle_sec if session_idle_sec is not None else SPEAK_SESSION_IDLE_SEC
        self._session_manager = SpeakSessionManager(
            presence=presence,
            semantic=self._semantic,
            idle_sec=idle,
            inner_lifecycle=session_lifecycle,
            touch_dialogue=touch_dialogue,
            registry=session_registry,
            reset_context=self.reset_context,
            memory_turn_gap=memory_turn_gap,
            guidance_control=self._guidance_control,
            brew_queue_max=director_brew_queue_max,
            typing_idle_ms=typing_idle_ms,
        )
        self._typing_idle_ms_default = typing_idle_ms
        self._delivery_mode = "stream"
        self._director_llm = director_llm_engine or SpeakDirectorLLMEngine()
        self._director: SessionDialogueDirector | None = None
        self._director_worker: DirectorWorker | None = None
        self._brew_dispatcher: BrewDispatcher | None = None
        self._director_push_now_cooldown_sec = director_push_now_cooldown_sec
        self._director_brew_queue_max = director_brew_queue_max
        self._session_manager.bind_record_fn(self.record_turn)
        self._session_manager.bind_compose_scheduler(
            lambda session_id, mode: self._schedule_compose_prepare(session_id, mode=mode),
        )
        self._session_manager.bind_queue_decision_scheduler(self._schedule_queue_decision)
        self._queue_decision_runner.set_complete_handler(
            self._session_manager.on_queue_decision_complete,
        )
        self._bind_session_social()
        self._inbound_hub = SpeakInboundHub(
            compose_runner=self._compose_runner,
            session_manager=self._session_manager,
            share_threshold=share_threshold,
            presence=presence,
            on_compose_prepare=self._on_compose_prepare_request,
            keyword_wait_ms=keyword_wait_ms,
            memory_budget=memory_budget,
            portrait_wait_ms=portrait_wait_ms,
        )
        channel = SpeakStreamChannel()
        typing_hold = SpeakTypingHoldEmitter(
            inner=channel.emit,
            enabled=True,
        )
        resolved_pipeline = stream_pipeline or SpeakStreamPipeline(
            flush_mode=flush_mode,
            emit_fn=typing_hold,
        )
        stream_hub = SpeakOutboundStreamHub(
            flush_mode=flush_mode,
            pipeline=resolved_pipeline,
            channel=channel,
        )
        self._typing_hold = typing_hold
        self._outbound_hub = SpeakOutboundHub(
            stream_hub,
            life=life_outbound,
        )
        self._io = SpeakIOHub(self._inbound_hub, self._outbound_hub)
        self._inbound_compose = self._io.inbound.compose
        self._inbound_memory = self._io.inbound.memory
        self._memory_compose = self._io.inbound.memory_compose
        self._drive = self._io.inbound.drive
        self._outbound_stream = self._io.outbound.stream.channel
        self._stream = self._io.outbound.stream.pipeline
        if orchestrator is not None:
            self._orchestrator = orchestrator
        elif persona is not None and presence is not None:
            threshold = share_threshold if share_threshold is not None else PROACTIVE_OPEN_THRESHOLD
            share_composer = ShareDesireComposer(
                proactive_threshold=threshold,
                session_share_reader=lambda sid: self._session_manager.deferred_share_intents(sid),
            )
            self._orchestrator = SpeakOrchestrator(
                persona,
                presence,
                share_threshold=threshold,
                share_composer=share_composer,
                context_distiller=self._context,
                status_store=self._inbound_compose.status_store,
                guidance_control=self._guidance_control,
            )
            from .orchestrator.session import RegistrySessionComposePort

            self._orchestrator.bind_session_port(
                RegistrySessionComposePort(self.session_registry)
            )
            self._guidance_io = self._orchestrator.io
        else:
            self._orchestrator = None
        if self._orchestrator is not None:
            self._bind_orchestrator_runtime()
            self._bind_orchestrator_interactor_portrait()
            self._turn_coordinator = OrchestratorTurnCoordinator(
                self._orchestrator,
                compose_runner=self._compose_runner,
            )
        else:
            self._turn_coordinator = None
        self._brew_dispatcher = BrewDispatcher(emit_fn=self._stream._emit)
        self._bind_session_director()
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

    def _bind_session_social(self) -> None:
        social = self._session_manager.social
        social.bind_dialogue_supplier(
            lambda sid: self.session_working_memory_block(sid),
        )
        social.bind_activity(
            is_active=self._session_manager.has_active_dialogue,
            is_pushing=self._session_manager.is_pushing,
        )
        social.silence.set_llm(self._llm)
        social.set_silence_break_handler(self._execute_silence_break)
        social.enter_greeting.set_llm(self._llm)
        social.set_enter_greeting_handler(self._execute_enter_greeting)

    def set_story_port(self, port, world_id_fn: Callable[[], str] | None = None) -> None:
        self._story_port = port
        self._world_id_fn = world_id_fn
        if self._orchestrator is not None:
            self._orchestrator.bind_story_port(port, world_id_fn)

    def _pop_session_share_at(self, session_id: str, queue_index: int) -> bool:
        intent = self._session_manager.queues.share_queue.pop_at(session_id, queue_index)
        return intent is not None

    def _mark_recall_unit_consumed(self, session_id: str, unit_id: str) -> None:
        if self._orchestrator is not None:
            self._orchestrator.memory_warm_buffer(session_id).mark_unit_consumed(
                session_id,
                unit_id,
            )
            return
        self._session_manager.queues.memory_queue.mark_unit_consumed(session_id, unit_id)

    def _bind_orchestrator_runtime(self) -> None:
        if self._orchestrator is None:
            return
        self._orchestrator.bind_memory_turn_gap(self._session_manager.queues.memory_turn_gap)
        self._session_manager.queues.bind_memory_warm_buffer(
            self._orchestrator.memory_warm_buffer,
        )
        self._memory_compose._recall_pick_weights = self._orchestrator
        original_open = self._session_manager.open
        original_clear = self._session_manager.queues.clear_session
        original_rotate = self._session_manager._starter._on_rotate

        def _open(session_id: str, **kwargs):
            result = original_open(session_id, **kwargs)
            self._orchestrator.start_session_compose_sync(session_id)
            return result

        def _clear(session_id: str) -> None:
            self._orchestrator.clear_session_compose_state(session_id)
            if self._turn_coordinator is not None:
                self._turn_coordinator.clear_session(session_id)
            if self._director is not None:
                self._director.clear_session(session_id)
            original_clear(session_id)

        def _on_rotate(session_id: str) -> None:
            original_rotate(session_id)
            self._orchestrator.start_session_compose_sync(session_id)

        self._session_manager.open = _open  # type: ignore[method-assign]
        self._session_manager.queues.clear_session = _clear  # type: ignore[method-assign]
        self._session_manager._starter._on_rotate = _on_rotate  # type: ignore[method-assign]

    def set_delivery_mode(self, mode: str) -> None:
        normalized = str(mode or "stream").strip().lower()
        if normalized not in ("stream", "simulated"):
            normalized = "stream"
        self._delivery_mode = normalized
        if self._typing_hold is not None:
            self._typing_hold.enabled = normalized != "simulated"

    def on_typing_pulse(
        self,
        session_id: str,
        *,
        typing: bool,
        draft: str = "",
    ) -> dict[str, object]:
        return self._session_manager.queues.on_typing_pulse(
            session_id,
            typing=typing,
            draft=draft,
        )

    def _bind_session_director(self) -> None:
        queues = self._session_manager.queues
        self._director = SessionDialogueDirector(
            queues=queues,
            director_llm=self._director_llm,
            push_now_cooldown_sec=self._director_push_now_cooldown_sec,
            brew_queue_max=self._director_brew_queue_max,
            deliver_push_now=self._deliver_push_now_line,
        )
        worker = DomainWorker("speak-director-worker")
        self._director_worker = DirectorWorker(
            worker=worker,
            director=self._director,
            build_input=self._build_director_input,
            collect_signals=self._collect_director_signals,
            on_idle_complete=self._on_typing_idle_complete,
        )
        queues.bind_typing_start(
            lambda sid: self._director_worker.schedule_trigger(sid, "typing_start"),
        )
        queues.bind_typing_idle(
            lambda sid: self._director_worker.schedule_trigger(sid, "typing_idle"),
        )

    def _build_director_input(self, session_id: str, trigger: str) -> DirectorInput:
        distill = ""
        wm = ""
        if self._context is not None:
            distill = self._context.context_distill_block(session_id)
            record = self.session_registry.get(session_id)
            wm = self._context.working_memory_block(
                session_id,
                generation=record.generation,
            )
        runtime = self._session_manager.queues._runtime(session_id)
        with runtime.lock:
            draft = runtime.draft_user_text
            typing_active = runtime.typing_active
            phase = runtime.phase
        signals = self._collect_director_signals(session_id)
        return DirectorInput(
            session_id=session_id,
            trigger=trigger,  # type: ignore[arg-type]
            typing_active=typing_active,
            draft_user_text=draft,
            phase=phase,
            context_distill=distill,
            working_memory=wm,
            share_wants=signals.share_wants,
            share_summary=signals.share_summary,
            share_queue_depth=signals.share_queue_depth,
            silence_armed=signals.silence_armed,
        )

    def _collect_director_signals(self, session_id: str):
        share_state = None
        deferred = 0
        if self._orchestrator is not None:
            share_state = self._orchestrator.share_compose_state(session_id)
            deferred = len(self._session_manager.deferred_share_intents(session_id))
        silence_armed = session_id.strip() in self._session_manager.social.silence._armed
        return self._director.collect_signals(
            session_id,
            share_state=share_state,
            deferred_share_count=deferred,
            silence_armed=silence_armed,
        )

    def _deliver_push_now_line(self, session_id: str, text: str) -> None:
        if self._brew_dispatcher is None:
            return
        self._outbound_stream.begin_session(session_id)
        self._brew_dispatcher._emit_brew_line(session_id, text)

    def _on_typing_idle_complete(self, session_id: str) -> None:
        if self._director is not None:
            self._director.reset_typing_segment(session_id)
        self._flush_brew_queue(session_id)
        self._session_manager.queues._runtime(session_id).typing_idle_handoff.set()

    def _flush_brew_queue(self, session_id: str) -> list[str]:
        lines = self._session_manager.queues.flush_brew(session_id)
        if not lines or self._brew_dispatcher is None:
            return lines
        self._outbound_stream.begin_session(session_id)
        return self._brew_dispatcher.drain(session_id, lines)

    def set_utterance_hold(
        self,
        session_id: str,
        *,
        enabled: bool,
        hold_ms: int = 3000,
    ):
        return self._session_manager.set_utterance_hold(
            session_id,
            enabled=enabled,
            hold_ms=hold_ms,
        )

    def _kick_for_upcoming_turn(self, session_id: str, user_text: str, turn_index: int) -> None:
        if self._turn_coordinator is None:
            return
        record = self.session_registry.get(session_id)
        self._turn_coordinator.kick_on_user_input(
            session_id,
            user_text,
            turn_index=turn_index,
            memory_compose=self._memory_compose,
            generation=record.generation,
        )

    def _before_compose_bundle(self, session_id: str, user_text: str) -> None:
        if self._turn_coordinator is None:
            return
        self._turn_coordinator.wait_before_compose(session_id)

    def _bind_orchestrator_interactor_portrait(self) -> None:
        if self._orchestrator is None:
            return
        self._orchestrator.bind_interactor_portrait_bridge(
            self._memory_compose,
            portrait_wait_ms=self._portrait_wait_ms,
        )

    def _apply_compose_context(self, bundle, *, similar, portrait) -> None:
        self._memory_compose.apply_similar_memories(bundle, similar)
        if self._orchestrator is not None:
            from .orchestrator.persona.interactor_portrait import (
                interactor_pull_from_memory_result,
            )

            pulled = interactor_pull_from_memory_result(portrait)
            self._orchestrator.interactor_portrait.apply_to_bundle(bundle, pulled)
        else:
            self._memory_compose.apply_interactor_portrait(bundle, portrait)

    def _refresh_interactor_portrait_on_bundle(
        self,
        session_id: str,
        bundle,
        turn_index: int,
    ) -> None:
        if self._orchestrator is not None:
            pulled = self._orchestrator.interactor_portrait.pull_for_compose(
                session_id,
                turn_index,
            )
            if pulled.portrait_text.strip() or pulled.display_name.strip():
                self._orchestrator.interactor_portrait.apply_to_bundle(bundle, pulled)
            return
        self._memory_compose.refresh_interactor_portrait_on_bundle(
            session_id,
            bundle,
            turn_index,
        )

    def _finish_turn_bundle(
        self,
        bundle: SpeakPromptBundle,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode,
        turn_index: int,
    ) -> SpeakPromptBundle:
        from .orchestrator.assemble import finish_turn_bundle
        from .orchestrator.session import RegistrySessionComposePort

        share_count = 0
        reconcile_plan = None
        session_port = RegistrySessionComposePort(self.session_registry)
        if self._orchestrator is not None:
            share_count = self._orchestrator.collect_share_count(session_id)
            reconcile_plan = self._orchestrator.reconcile_compose(
                bundle,
                session_id=session_id,
            )
        presence = self._presence
        if self._orchestrator is not None:
            record = self.session_registry.get(session_id)
            self._orchestrator.attach_session_context(
                bundle,
                session_id,
                generation=record.generation,
            )
        finished = finish_turn_bundle(
            bundle,
            social=self._session_manager.social,
            session_id=session_id,
            user_text=user_text,
            turn_index=turn_index,
            mode=mode,
            story_port=self._story_port,
            world_id_fn=self._world_id_fn,
            io=self._guidance_io,
            share_queue_count=share_count,
            share_state=(
                self._orchestrator.share_compose_state(session_id)
                if self._orchestrator is not None
                else None
            ),
            use_session_share_queue=(
                self._orchestrator.uses_session_share_queue(session_id)
                if self._orchestrator is not None
                else False
            ),
            pop_presence_share_at=(
                presence.consume_share_at
                if presence is not None
                else None
            ),
            pop_session_share_at=self._pop_session_share_at,
            mark_recall_unit_consumed=self._mark_recall_unit_consumed,
            session_port=session_port,
            reconcile_plan=reconcile_plan,
        )
        if self._orchestrator is not None:
            self._orchestrator.touch_compose_cache_from_meta(session_id, finished.meta)
        if self._turn_coordinator is not None:
            finished.meta["turn_coordinator"] = self._turn_coordinator.state(
                session_id,
            ).snapshot()
            finished.meta["module_refresh"] = finished.meta["turn_coordinator"].get(
                "module_refresh",
            )
        if self._director is not None:
            finished.meta["session_director"] = self._director.state(session_id).snapshot()
            brew_hint = self._director.recent_brew_summary(session_id)
            if brew_hint:
                finished.meta["recent_brew_lines"] = brew_hint
        finished.meta["session_typing"] = self._session_manager.queues._runtime(
            session_id,
        ).snapshot_typing()
        finished.meta["session_brew_queue"] = self._session_manager.queues.brew_queue_snapshot(
            session_id,
        )
        return finished

    def _execute_enter_greeting(self, spec) -> None:
        from .orchestrator.guidance.social import resolve_enter_greeting_user_text
        from .session.manage.types import EnterGreetingTurnSpec

        assert isinstance(spec, EnterGreetingTurnSpec)
        session_id = spec.session_id.strip()
        if not session_id:
            return
        if self._session_manager.is_pushing(session_id):
            return
        if self._session_manager.user_queue.has_pending(session_id):
            return
        self._session_manager.social.arm_enter_greeting(spec)
        stream = self._outbound_stream.port is not None
        prelude = spec.angle.strip() or spec.thought.strip()
        if stream and prelude:
            self.enqueue_proactive_brew(
                session_id,
                prelude,
                reason="enter_greeting",
                flush_if_idle=not self._session_manager.queues.is_typing_without_idle(
                    session_id,
                ),
            )
        if stream:
            self._flush_brew_queue(session_id)
        self.run_turn(
            session_id,
            resolve_enter_greeting_user_text(spec),
            stream=stream,
            mode="proactive",
            record=True,
        )

    def arm_enter_greeting(self, session_id: str) -> None:
        self._session_manager.social.enter_greeting.arm_session(session_id.strip())

    def cancel_enter_greeting(self, session_id: str) -> None:
        self._session_manager.social.enter_greeting.cancel_session(session_id.strip())

    def seed_warm_spread(self, session_id: str, *, lines: list[str], unit_ids: list[str]) -> None:
        if not unit_ids:
            return
        self._session_manager.set_warm_spread(
            session_id,
            lines=list(lines),
            unit_ids=list(unit_ids),
        )

    def _execute_silence_break(self, spec: SilenceBreakTurnSpec) -> None:
        from .orchestrator.guidance.social import resolve_silence_break_user_text

        session_id = spec.session_id.strip()
        if not session_id:
            return
        if self._session_manager.is_pushing(session_id):
            return
        if self._session_manager.user_queue.has_pending(session_id):
            return
        if not self._session_manager.has_active_dialogue(session_id):
            return
        self._session_manager.social.arm_silence_break(spec)
        stream = self._outbound_stream.port is not None
        prelude = spec.angle.strip() or spec.thought.strip()
        if stream and prelude:
            self.enqueue_proactive_brew(
                session_id,
                prelude,
                reason="silence_break",
                flush_if_idle=not self._session_manager.queues.is_typing_without_idle(
                    session_id,
                ),
            )
        if stream:
            self._flush_brew_queue(session_id)
        self.run_turn(
            session_id,
            resolve_silence_break_user_text(spec),
            stream=stream,
            mode="inbound",
            record=True,
        )

    @property
    def llm_engine(self) -> SpeakLLMEngine:
        return self._llm

    @property
    def orchestrator(self) -> SpeakOrchestrator | None:
        return self._orchestrator

    @property
    def compose_runner(self) -> SpeakComposeRunner:
        return self._compose_runner

    @property
    def queue_decision_runner(self) -> QueueDecisionRunner:
        return self._queue_decision_runner

    def start(self) -> None:
        self._compose_runner.start()
        self._queue_decision_runner.start()
        if self._director_worker is not None:
            self._director_worker.start_worker()
        self._session_manager.social.silence.start_worker()
        self._session_manager.social.enter_greeting.start_worker()
        self._schedule_compose_prepare("tao")

    def stop(self) -> None:
        self._session_manager.social.silence.stop_worker()
        self._session_manager.social.enter_greeting.stop_worker()
        if self._director_worker is not None:
            self._director_worker.stop_worker()
        self._queue_decision_runner.stop()
        self._compose_runner.stop()

    @property
    def life_outbound(self) -> SpeakLifeOutboundBridge | None:
        return self._life_outbound

    @property
    def stream_pipeline(self) -> SpeakStreamPipeline:
        return self._stream

    @property
    def outbound_stream(self) -> SpeakStreamChannel:
        return self._outbound_stream

    @property
    def session_registry(self) -> SpeakSessionRegistry:
        return self._session_manager.registry

    @property
    def inbound_compose(self) -> InboundComposeGateway:
        return self._inbound_compose

    @property
    def io(self) -> SpeakIOHub:
        return self._io

    @property
    def inbound_memory(self) -> InboundMemoryGateway:
        return self._inbound_memory

    @property
    def memory_compose(self):
        return self._memory_compose

    @property
    def session_manager(self) -> SpeakSessionService:
        return self._session_manager

    @property
    def drive_bridge(self) -> SpeakDriveBridge:
        return self._drive

    @property
    def dialogue_bridge(self) -> SpeakDialogueBridge:
        return self._dialogue_bridge

    @property
    def context_distiller(self) -> SpeakContextDistiller | None:
        return self._context

    def set_session_prompt_trace(self, session_id: str, enabled: bool) -> dict[str, object]:
        trace = get_prompt_trace()
        trace.set_session(session_id, enabled)
        return {
            "session_id": session_id.strip(),
            "enabled": trace.is_enabled(session_id),
            "global": trace.global_enabled,
        }

    def get_session_prompt_trace(self, session_id: str) -> dict[str, object]:
        trace = get_prompt_trace()
        return {
            "session_id": session_id.strip(),
            "enabled": trace.is_enabled(session_id),
            "global": trace.global_enabled,
            "traced_sessions": trace.enabled_sessions(),
        }

    @property
    def guidance_control(self) -> GuidanceControlService:
        return self._guidance_control

    @property
    def orchestrator_io(self) -> OrchestratorIOHub:
        return self._guidance_io

    def clear_guidance_control_arc(self, session_id: str) -> None:
        if self._orchestrator is not None:
            self._orchestrator.clear_guidance_control_arc(session_id.strip())
            return
        self._guidance_io.inbound.guidance.clear_control_arc(session_id.strip())

    def get_guidance_control(self, session_id: str) -> dict[str, object] | None:
        return self._guidance_io.outbound.guidance.snapshot(session_id.strip())

    def guidance_control_version(self, session_id: str) -> int | None:
        return self._guidance_io.outbound.guidance.version(session_id.strip())

    def refresh_guidance_control(
        self,
        session_id: str,
        *,
        turn_index: int | None = None,
        share_queue_count: int | None = None,
    ) -> dict[str, object] | None:
        from .orchestrator.io.inbound.guidance import GuidancePlanRequest

        sid = session_id.strip()
        resolved_turn = (
            turn_index
            if turn_index is not None
            else self.session_registry.current_turn_index(sid)
        )
        count = share_queue_count
        if count is None and self._orchestrator is not None:
            count = self._orchestrator.collect_share_count(sid)
        count = count or 0
        request = GuidancePlanRequest(
            session_id=sid,
            turn_index=resolved_turn,
            share_queue_count=count,
            share_queue_full=self._guidance_io.inbound.guidance.share_queue_full(count),
            trigger="manual",
        )
        self._guidance_io.inbound.guidance.plan(request)
        return self.get_guidance_control(sid)

    def session_trace_cache(
        self,
        session_id: str,
        *,
        turn_index: int | None = None,
    ) -> dict[str, object]:
        resolved_turn = (
            turn_index
            if turn_index is not None
            else self.session_registry.current_turn_index(session_id)
        )
        record = self.session_registry.get(session_id)
        distill: dict[str, object] = {}
        if self._context is not None:
            distill = self._context.snapshot(session_id)
        return {
            "session_id": session_id,
            "turn_index": resolved_turn,
            "generation": record.generation,
            "bound_interactor": self.session_registry.get_bound_interactor(session_id),
            "distiller": distill,
            "queues": self._session_manager._queues.debug_snapshot(session_id),
        }

    def reset_context(self, session_id: str) -> None:
        self._inbound_compose.reset_session(session_id)
        self._session_manager.clear_compose(session_id)
        if self._context is not None:
            self._context.reset_session(session_id)
        if self._orchestrator is not None:
            self._orchestrator.clear_persona_compose(session_id)
            self._orchestrator.clear_guidance_control_arc(session_id)
        if self._presence is not None:
            self._presence.apply_dialogue_session_boundary(session_id)

    def session_working_memory_block(
        self,
        session_id: str,
        *,
        generation: int | None = None,
    ) -> str:
        if self._context is None:
            return ""
        record = self.session_registry.get(session_id)
        gen = record.generation if generation is None else generation
        return self._context.working_memory_block(session_id, generation=gen)

    def attach_memory_keyword_query(self, keyword_query_fn) -> None:
        self._io.inbound.attach_memory_ports(keyword_query_fn=keyword_query_fn)

    def attach_memory_recall(self, recall_fn) -> None:
        self._io.inbound.attach_memory_ports(recall_fn=recall_fn)

    def attach_memory_point_query(self, point_query_fn) -> None:
        self._io.inbound.attach_memory_ports(point_query_fn=point_query_fn)

    def attach_memory_pull_similar(self, pull_similar_fn) -> None:
        self._io.inbound.attach_memory_ports(pull_similar_fn=pull_similar_fn)

    def attach_memory_portrait_query(self, portrait_query_fn) -> None:
        self._io.inbound.attach_memory_ports(portrait_query_fn=portrait_query_fn)

    def attach_memory_pull_portrait(self, pull_portrait_fn) -> None:
        self._io.inbound.attach_memory_ports(pull_portrait_fn=pull_portrait_fn)

    def bind_interactor(self, session_id: str, interactor_id: str) -> None:
        self.session_registry.bind_interactor(session_id, interactor_id)

    def _on_compose_prepare_request(self, request: ComposePrepareRequest) -> None:
        if self._orchestrator is None:
            return
        self._compose_runner.schedule_prepare(
            self._orchestrator,
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

    def refresh_share_expectation_thresholds(self) -> None:
        """presence 档位热更新后，同步 speak drive / compose 的 proactive 阈值。"""
        from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD

        threshold = PROACTIVE_OPEN_THRESHOLD
        if self._orchestrator is not None:
            self._orchestrator._share._threshold = threshold
        if self._inbound_hub is not None:
            self._inbound_hub.drive.share_threshold = threshold
            self._inbound_hub.drive._share._threshold = threshold

    def set_stream_port(self, port: SpeakStreamPort | None) -> None:
        self._io.outbound.bind_stream_port(port)
        if port is None:
            return
        mode = self._resolve_delivery_mode_from_port(port)
        self.set_delivery_mode(mode)

    @staticmethod
    def _resolve_delivery_mode_from_port(port: SpeakStreamPort) -> str:
        name = type(port).__name__
        if name == "SimulatedTypingStreamPort":
            return "simulated"
        inner = getattr(port, "inner", None)
        if inner is not None and type(inner).__name__ == "SimulatedTypingStreamPort":
            return "simulated"
        return "stream"

    def director_snapshot(self, session_id: str) -> dict[str, object]:
        sid = session_id.strip()
        out: dict[str, object] = {
            "session_id": sid,
            "delivery_mode": self._delivery_mode,
            "director_llm_ready": self._director_llm.available,
        }
        if self._director is not None:
            out["director"] = self._director.state(sid).snapshot()
        out["typing"] = self._session_manager.queues._runtime(sid).snapshot_typing()
        out["brew_queue"] = self._session_manager.queues.brew_queue_snapshot(sid)
        return out

    def enqueue_proactive_brew(
        self,
        session_id: str,
        text: str,
        *,
        reason: str = "proactive",
        flush_if_idle: bool = True,
    ) -> dict[str, object]:
        sid = session_id.strip()
        line = text.strip()
        if not line:
            return {"ok": False, "reason": "empty_text"}
        queued = self._session_manager.queues.enqueue_brew(sid, line, reason=reason)
        flushed: list[str] = []
        if flush_if_idle and not self._session_manager.queues.is_typing_without_idle(sid):
            flushed = self._flush_brew_queue(sid)
        if self._director_worker is not None and not flushed:
            self._director_worker.schedule_trigger(sid, "rule_share")
        return {
            "ok": queued,
            "reason": reason,
            "flushed": flushed,
            "brew_queue": self._session_manager.queues.brew_queue_snapshot(sid),
        }

    def ingest_deferred_share_for_director(
        self,
        session_id: str,
        intents,
    ) -> dict[str, object]:
        """Presence 延迟分享入队后，同步写入导演酝酿队列。"""
        sid = session_id.strip()
        lines: list[str] = []
        for intent in intents or ():
            topic = str(getattr(intent, "topic", "") or "").strip()
            if not topic:
                topic = str(getattr(intent, "summary", "") or "").strip()
            if topic:
                lines.append(topic[:40])
        notes: list[str] = []
        for line in lines:
            self._session_manager.queues.enqueue_brew(sid, line, reason="deferred_share")
            notes.append(f"brew: {line[:24]}")
        if self._director_worker is not None:
            self._director_worker.schedule_trigger(sid, "rule_share")
        return {
            "session_id": sid,
            "lines": lines,
            "notes": notes,
            "brew_queue": self._session_manager.queues.brew_queue_snapshot(sid),
        }

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
        turn_index: int | None = None,
    ) -> SpeakPromptBundle:
        resolved_turn = (
            turn_index
            if turn_index is not None
            else self.session_registry.current_turn_index(session_id)
        )
        ledger = None
        if self._turn_coordinator is not None:
            ledger = self._turn_coordinator.inject_ledgers.ledger(
                session_id,
                resolved_turn,
            )
        pulled, portrait_pulled = self._memory_compose.pull_compose_context(
            session_id,
            user_text=user_text,
            turn_index=resolved_turn,
            ledger=ledger,
        )

        if self._orchestrator is None:
            from .orchestrator import (
                SpeakGuidanceLayer,
                SpeakPersonaLayer,
                SpeakSceneLayer,
                build_system_layer,
                collect_persona_layer,
            )

            presence_snap = self._presence.snapshot(session_id) if self._presence is not None else None
            persona = (
                collect_persona_layer(
                    persona_snap=self._persona.get_persona_snapshot(session_id=session_id),
                    presence_snap=presence_snap,
                )
                if presence_snap is not None and self._persona is not None
                else SpeakPersonaLayer()
            )

            bundle = SpeakPromptBundle(
                session_id=session_id,
                mode=mode,
                system=build_system_layer(
                    mode=mode,
                    output_format=self._reply_style.render_prompt(),
                ),
                persona=persona,
                scene=SpeakSceneLayer(),
                guidance=SpeakGuidanceLayer(),
                user_text=user_text.strip(),
                reply_style=self._reply_style,
            )
            record = self.session_registry.get(session_id)
            if self._context is not None:
                bundle.guidance.context_distill = self._context.context_distill_block(
                    session_id,
                )
                bundle.guidance.working_memory = self._context.working_memory_block(
                    session_id,
                    generation=record.generation,
                )
                raw = self._context.prompt_block(session_id)
                if raw:
                    bundle.persona.dialogue_compressed = raw
            self._apply_compose_context(
                bundle,
                similar=pulled,
                portrait=portrait_pulled,
            )
            return self._finish_turn_bundle(
                bundle,
                session_id,
                user_text,
                mode=mode,
                turn_index=resolved_turn,
            )

        queued = self._session_manager.pop_compose(session_id, mode=mode)
        if queued is not None:
            bundle = self._orchestrator.finalize(queued.frame, user_text, session_id=session_id)
            bundle.meta["compose_source"] = "session_queue"
            self._apply_compose_context(
                bundle,
                similar=pulled,
                portrait=portrait_pulled,
            )
            return self._finish_turn_bundle(
                bundle,
                session_id,
                user_text,
                mode=mode,
                turn_index=resolved_turn,
            )

        frame = self._compose_runner.take_ready_frame(session_id, mode=mode)
        if frame is not None:
            bundle = self._orchestrator.finalize(frame, user_text, session_id=session_id)
            self._apply_compose_context(
                bundle,
                similar=pulled,
                portrait=portrait_pulled,
            )
            return self._finish_turn_bundle(
                bundle,
                session_id,
                user_text,
                mode=mode,
                turn_index=resolved_turn,
            )

        bundle = self._orchestrator.compose(
            session_id,
            user_text,
            mode=mode,
            reply_style=self._reply_style,
            generation=self.session_registry.get(session_id).generation,
        )
        bundle.meta["compose_source"] = "sync_fallback"
        self._apply_compose_context(
            bundle,
            similar=pulled,
            portrait=portrait_pulled,
        )
        return self._finish_turn_bundle(
            bundle,
            session_id,
            user_text,
            mode=mode,
            turn_index=resolved_turn,
        )

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
        turn_index: int | None = None,
    ) -> SpeakPromptBundle | None:
        if self._orchestrator is None:
            return None
        queued = self._session_manager.pop_compose(session_id, mode=mode)
        if queued is None:
            return None
        bundle = self._orchestrator.finalize(queued.frame, user_text, session_id=session_id)
        bundle.meta["compose_source"] = "session_queue"
        resolved_turn = (
            turn_index
            if turn_index is not None
            else self.session_registry.current_turn_index(session_id)
        )
        pulled = self._memory_compose.pull_similar_memories(
            session_id,
            resolved_turn,
            user_text=user_text,
        )
        portrait_pulled = self._memory_compose.pull_interactor_portrait(session_id, resolved_turn)
        self._apply_compose_context(
            bundle,
            similar=pulled,
            portrait=portrait_pulled,
        )
        return bundle

    def _generate_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
    ) -> tuple[str, list[SpeakStreamEvent]]:
        return self._io.outbound.stream.generate_turn(
            self._llm,
            session_id,
            user_text,
            system=system,
            stream=stream,
        )

    def _continue_share_handoff(
        self,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
        notes: list[str],
    ) -> tuple[str, list[SpeakStreamEvent], SpeakAgentOutput] | None:
        if self._presence is None or self._orchestrator is None:
            notes.append("share handoff: no presence/orchestrator")
            return None

        handoff = self._orchestrator.share.pop_handoff(
            self._presence,
            session_id,
            pop_deferred=self._session_manager.pop_deferred_share_intent,
        )
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
            self._io.inbound.memory,
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
        self._session_manager.open(session_id, trigger="user_message")
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

        upcoming = self.session_registry.current_turn_index(session_id) + 1
        self._kick_for_upcoming_turn(session_id, user_text, upcoming)

        waited_typing = self._session_manager.queues.is_typing_without_idle(session_id)
        if waited_typing:
            user_text = self._session_manager.queues.merge_pending_user_text(
                session_id,
                user_text,
            )
            self._session_manager.queues.wait_typing_idle(session_id, timeout=120.0)
            self._session_manager.queues.wait_typing_idle_handoff(
                session_id,
                timeout=120.0,
            )
        else:
            self._flush_brew_queue(session_id)

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
            begin_turn=self._session_manager.begin_turn,
            refresh_similar_memories=self._memory_compose.refresh_similar_memories_after_turn,
            refresh_interactor_portrait=self._refresh_interactor_portrait_on_bundle,
            llm=self._llm,
            stream_pipeline=self._stream,
            outbound_stream=self._outbound_stream,
            record_turn=self.record_turn,
            schedule_compose=lambda sid: self._schedule_compose_prepare(sid, mode=item.mode),
            resolve_interactor_id=lambda sid: self.session_registry.get_bound_interactor(sid),
            continue_share_handoff=self._continue_share_handoff,
            continue_recall_handoff=self._continue_recall_handoff,
            compose_from_queue=self._compose_from_queue,
            parse_agent_output=parse_agent_output,
            session_trace_cache=lambda sid, ti: self.session_trace_cache(sid, turn_index=ti),
            before_compose_bundle=self._before_compose_bundle,
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
        if self._story_port is not None and self._world_id_fn is not None:
            world_id = self._world_id_fn().strip()
            user_text = chunk.user_text.strip()
            if world_id and user_text:
                self._story_port.service.push_cue(world_id, user_text)
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
        stream_port = self._outbound_stream.port
        brew_meta: dict[str, object] = {}
        if stream_port is not None and len(text) <= 120:
            brew_meta = self.enqueue_proactive_brew(
                session_id,
                text,
                reason="proactive_outbound",
                flush_if_idle=True,
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
            "brew": brew_meta,
        }

    def drive_snapshot(self, session_id: str) -> SpeakDriveSnapshot:
        return self._drive.snapshot(session_id)

    def evaluate_drive(self, session_id: str) -> SpeakDriveResult:
        result = self._drive.evaluate(session_id)
        if result.should_speak and result.speak_reason.strip():
            if self._session_manager.is_pushing(session_id):
                self.enqueue_proactive_brew(
                    session_id,
                    result.speak_reason,
                    reason="drive_while_pushing",
                    flush_if_idle=False,
                )
            elif self._outbound_stream.port is not None:
                self.enqueue_proactive_brew(
                    session_id,
                    result.speak_reason,
                    reason="drive_eval",
                    flush_if_idle=not self._session_manager.queues.is_typing_without_idle(
                        session_id,
                    ),
                )
        return result

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
