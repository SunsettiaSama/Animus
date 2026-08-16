from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.speak.io.inbound.memory.recall import perform_recall_handoff
from agent.soul.workers import DomainWorker

from .responders.request_driven.orchestrator import (
    ShareDesireComposer,
    SpeakContextDistiller,
    SpeakOrchestrator,
    SpeakPromptBundle,
    SpeakReplyStyle,
    SpeakTurnMode,
)
from .responders.request_driven.orchestrator.blocks.guidance import GuidanceControlService
from .responders.request_driven.orchestrator.io import OrchestratorIOHub
from .responders.request_driven.orchestrator.runner import SpeakComposeRunner
from config.soul.presence.config import PROACTIVE_OPEN_THRESHOLD
from .io.hub import SpeakIOHub
from .io.inbound import SpeakDialogueBridge, SpeakIngestResult, SpeakInboundPort, ingest_question
from .io.inbound.compose.gateway import InboundComposeGateway
from .io.inbound.compose.request import ComposePrepareRequest
from .io.inbound.drive import SpeakDriveBridge, SpeakDriveResult, SpeakDriveSnapshot
from .io.inbound.memory import InboundMemoryGateway, SimilarMemoryPullResult
from .session import SpeakSessionManager, SpeakSessionService
from .session.queue import UserInputItem
from .session.turn import SessionTurnHost
from .responders import SpeakResponderRouter, normalize_speak_responder
from .responders.legacy_qa import LegacyQAPipelineRunner
from .responders.request_driven import RequestDrivenPipelineRunner
from .responders.rhythm import RhythmPipelineRunner
from .responders.rhythm.state import RhythmStateStore
from .responders.request_driven.orchestrator.queue import QueueDecisionRunner
from .responders.request_driven.orchestrator.prompt_trace import get_prompt_trace
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
from .responders.request_driven.orchestrator.turn_coordinator import OrchestratorTurnCoordinator
from .responders.request_driven.directors import (
    DirectorCoordinator,
    DirectorLLMCaller,
)
from .responders.request_driven.screenwriter import Screenwriter
from .responders.request_driven.orchestrator.runtime import DeliveryExecutor, OrchestratorThread
from .responders.request_driven.orchestrator.state import SnapshotBuilder, StateStore, print_session_snapshot
from .responders.request_driven.composer import (
    ComposeManager,
    ComposeManagerConfig,
    ComposeManagerGateway,
)
from .responders.request_driven.composer.ports.adapters import (
    CallableMemorySearchPort,
    PresenceShareHintPort,
    units_from_recall_candidates,
)
from .responders.request_driven.composer.ports.memory import MemoryHint, MemoryUnit
from .io.outbound.manager import message_from_request
from .io.outbound.protocol import OutboundRequest
from .responders.request_driven.delivery_bridge import timeline_to_outbound_request
from .responders.request_driven.directors.agent import DirectorAgentHost
from .responders.request_driven.character import CharacterAgentHost, CharacterRuntime
from .responders.request_driven import SpeakRole
from .io.outbound.character import CharacterWorkGateway, CharacterWorkPort
from .session.snapshot_port import RegistrySessionSnapshotPort
from .session.ingress import SessionOrchestratorIngress
from .llm.director_engine import SpeakDirectorLLMEngine
from .ports import SpeakDrivePort

if TYPE_CHECKING:
    from agent.soul.presence import PresenceService, PresenceSnapshot
    from .io.outbound import SpeakRequest

logger = logging.getLogger(__name__)

_OPENING_PLACEHOLDER = "（场面铺开中）"
_OPENING_SLOT = "narrative_opening"


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
        compose_manager_enabled: bool | None = None,
        compose_manager_config: ComposeManagerConfig | None = None,
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
            brew_queue_max=director_brew_queue_max,
            typing_idle_ms=typing_idle_ms,
        )
        self._typing_idle_ms_default = typing_idle_ms
        self._delivery_mode = "stream"
        self._director_llm = director_llm_engine or SpeakDirectorLLMEngine()
        self._state_store = StateStore()
        self._rhythm_store = RhythmStateStore()
        self._snapshot_port: RegistrySessionSnapshotPort | None = None
        self._snapshot_builder: SnapshotBuilder | None = None
        self._director_coordinator: DirectorCoordinator | None = None
        self._orchestrator_thread: OrchestratorThread | None = None
        self._session_ingress: SessionOrchestratorIngress | None = None
        self._delivery_executor: DeliveryExecutor | None = None
        self._delivery_worker = DomainWorker("speak-delivery-worker", owner="speak")
        self._director_llm_caller = DirectorLLMCaller()
        self._director_push_now_cooldown_sec = director_push_now_cooldown_sec
        self._director_brew_queue_max = director_brew_queue_max
        self._async_ready_sessions: deque[str] = deque()
        self._async_ready_guard = threading.Lock()
        self._character_handoff_inflight: set[str] = set()
        self._character_handoff_guard = threading.Lock()
        self._session_manager.bind_record_fn(self.record_turn)
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
        resolved_stream_pipeline = stream_pipeline or SpeakStreamPipeline(
            flush_mode=flush_mode,
            emit_fn=typing_hold,
        )
        stream_hub = SpeakOutboundStreamHub(
            flush_mode=flush_mode,
            pipeline=resolved_stream_pipeline,
            channel=channel,
        )
        self._typing_hold = typing_hold
        self._outbound_hub = SpeakOutboundHub(
            stream_hub,
            life=life_outbound,
        )
        self._outbound_manager = self._outbound_hub.manager
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
            self._guidance_io = self._orchestrator.io
        else:
            raise RuntimeError("SpeakService 需要 orchestrator 或 persona+presence")
        self._bind_orchestrator_runtime()
        self._bind_orchestrator_interactor_portrait()
        self._turn_coordinator = OrchestratorTurnCoordinator(
            self._orchestrator,
            compose_runner=self._compose_runner,
        )
        self._bind_compose_manager_sidechain(
            enabled=compose_manager_enabled,
            config=compose_manager_config,
        )
        self._bind_director_system()
        self._compose_runner.set_frame_ready_handler(
            lambda frame, mode: self._orchestrator.compose_queue_hub.on_frame_ready(
                frame, mode=mode,
            ),
        )
        self._bind_responder_router()

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

    def _bind_responder_router(self) -> None:
        legacy_host = SessionTurnHost(
            compose_bundle=self._compose_bundle,
            begin_turn=self._session_manager.begin_turn,
            llm=self._llm,
            stream_pipeline=self._stream,
            outbound_stream=self._outbound_stream,
            record_turn=self._session_manager.record_turn,
            schedule_compose=lambda sid: self._schedule_compose_prepare(sid),
            refresh_similar_memories=self._memory_compose.refresh_similar_memories_after_turn,
            refresh_interactor_portrait=self._refresh_interactor_portrait_on_bundle,
            continue_share_handoff=self._continue_share_handoff,
            continue_recall_handoff=self._continue_recall_handoff,
            compose_from_queue=self._compose_from_queue,
            parse_agent_output=parse_agent_output,
            session_trace_cache=lambda sid, turn_index: self.session_trace_cache(
                sid,
                turn_index=turn_index,
            ),
            before_compose_bundle=self._before_compose_bundle,
            on_turn_complete_hook=self._on_compose_turn_complete,
        )
        self._rhythm_runner = RhythmPipelineRunner(
            compose_bundle=self._compose_bundle,
            llm=self._llm,
            stream_pipeline=self._stream,
            outbound_stream=self._outbound_stream,
            rhythm_store=self._rhythm_store,
            director_generate=self._rhythm_director_generate,
            current_turn_index=self.session_registry.current_turn_index,
            begin_turn=self._session_manager.begin_turn,
            record_dialogue=self.record_dialogue,
            on_turn_complete=self._on_compose_turn_complete,
            peek_share=self._session_manager.queues.share_queue.peek_session,
            pop_share_at=self._session_manager.queues.share_queue.pop_at,
            typing_snapshot=self._rhythm_typing_snapshot,
            working_memory=self.session_working_memory_block,
            context_distill=self._rhythm_context_distill,
            affect_every_k=2,
            on_scene_every_k=3,
        )
        self._responder_router = SpeakResponderRouter(
            legacy_qa=LegacyQAPipelineRunner(
                manager=self._session_manager,
                host=legacy_host,
                interrupt_context_for=self._session_manager.interrupt_context_for,
            ),
            request_driven=RequestDrivenPipelineRunner(
                run_request_driven_turn=self._run_request_driven_turn,
            ),
            rhythm=self._rhythm_runner,
        )

    def _rhythm_director_generate(self, system: str, user: str) -> str:
        raw = self._director_llm_caller.generate_json(
            system=system,
            user=user,
            director="rhythm",
        ).strip()
        if not raw:
            raw = self._llm.generate(user, system=system).text.strip()
        if not raw:
            raise RuntimeError("rhythm director: empty LLM output")
        return raw

    def _rhythm_typing_snapshot(self, session_id: str) -> dict[str, object]:
        runtime = self._session_manager.queues._runtime(session_id)
        with runtime.lock:
            snap = dict(runtime.snapshot_typing())
            snap["push_phase"] = runtime.phase
        return snap

    def _rhythm_context_distill(self, session_id: str) -> str:
        if self._context is None:
            return ""
        return self._context.context_distill_block(session_id)

    def review_rhythm_session(self, session_id: str) -> dict[str, object]:
        return self._rhythm_runner.review_session(session_id)

    def _bind_session_social(self) -> None:
        social = self._session_manager.social
        # 静默开口只由 character rhythm schedule 调度，避免旧 90s silence-break
        # 以一次伪入站重写 0/5/15/30 阶梯，造成连续重复开口。
        social.silence_break_enabled = False
        social.bind_dialogue_supplier(
            lambda sid: self.session_working_memory_block(sid),
        )
        social.bind_activity(
            is_active=self._session_manager.has_active_dialogue,
            is_pushing=self._session_manager.is_pushing,
        )
        social.enter_greeting.set_llm(self._llm)
        social.set_enter_greeting_handler(self._execute_enter_greeting)

    def set_story_port(self, port, world_id_fn: Callable[[], str] | None = None) -> None:
        self._story_port = port
        self._world_id_fn = world_id_fn
        self._orchestrator.bind_story_port(port, world_id_fn)
        if getattr(self, "_screenwriter", None) is not None:
            self._screenwriter.bind_story(
                port,
                world_id_fn,
                scene_brief_fn=lambda sid: self._orchestrator.scene_compose.director_scene_brief(sid),
                resolve_scene_id_fn=self._resolve_active_scene_id,
            )

    def _resolve_active_scene_id(self, session_id: str) -> str:
        active = self._orchestrator.scene_compose.active(session_id)
        if active is None:
            return ""
        return str(active.result.scene_id or "").strip()

    def ensure_screenwriter_init(self, session_id: str) -> None:
        """会话打开：编剧写弧 + 场记 + opening。

        可同步调用；arm_enter_greeting 走后台线程，避免卡住 WS/热路径。
        """
        from .responders.request_driven.orchestrator.state.core.speak_dormant import (
            clear_narrative_for_reinit,
            needs_narrative_reinit,
        )

        sid = session_id.strip()
        if not sid or self._state_store is None or getattr(self, "_screenwriter", None) is None:
            return
        state = self._state_store.session(sid)
        if needs_narrative_reinit(state):
            clear_narrative_for_reinit(state)
        if state.presence_card.ready and state.plot_arc.ready:
            self._maybe_deliver_narrative_opening(sid)
            return
        self._screenwriter.init_presence(
            state,
            session_id=sid,
            turn_index=0,
            background_agent=True,
        )
        self._maybe_deliver_narrative_opening(sid)

    def _schedule_screenwriter_init(self, session_id: str) -> None:
        """后台跑编剧开场：前端先收占位 outline，完成后再升级推送。"""
        sid = session_id.strip()
        if not sid or self._state_store is None:
            return
        state = self._state_store.session(sid)
        if bool(state.director_cache.get("screenwriter_init_scheduled")):
            return
        state.director_cache["screenwriter_init_scheduled"] = True
        # 前端先渲染占位，不等编剧
        self._deliver_narrative_outline(
            sid,
            text=_OPENING_PLACEHOLDER,
            placeholder=True,
        )

        def _run() -> None:
            self.ensure_screenwriter_init(sid)
            # 真正 opening 只由 on_ready 推，这里不再二次投递
            state.director_cache.pop("screenwriter_init_scheduled", None)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"screenwriter-init-{sid[:16]}",
        ).start()

    def _deliver_narrative_outline(
        self,
        session_id: str,
        *,
        text: str,
        placeholder: bool = False,
        upgrade: bool = False,
    ) -> None:
        """推送编剧 opening（outline）。placeholder 先占位；upgrade 覆盖占位。"""
        from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest

        sid = session_id.strip()
        body = str(text or "").strip()
        if not sid or not body or self._state_store is None:
            return
        if not self._has_live_stream_session(sid):
            return
        state = self._state_store.session(sid)
        if placeholder and bool(state.director_cache.get("narrative_opening_placeholder_sent")):
            return
        already = bool(state.director_cache.get("narrative_opening_delivered"))
        prev = str(state.director_cache.get("narrative_opening") or "").strip()
        if not placeholder and already and prev == body:
            return
        if upgrade and prev == body and not placeholder:
            return
        if already and not placeholder and not upgrade:
            return

        state.director_cache["narrative_opening"] = body
        if placeholder:
            state.director_cache["narrative_opening_placeholder_sent"] = True
            state.director_cache["narrative_opening_is_placeholder"] = True
        else:
            first_ready = not bool(state.director_cache.get("narrative_opening_ready"))
            state.director_cache["narrative_opening_is_placeholder"] = False
            state.director_cache["narrative_opening_delivered"] = True
            state.director_cache["narrative_opening_ready"] = True
            if first_ready:
                self._nudge_after_opening_ready(sid)

        meta = {
            "field": "outline",
            "tag": "outline",
            "order": 0,
            "slot": _OPENING_SLOT,
            "placeholder": bool(placeholder),
            "upgrade": bool(upgrade),
            "replace": bool(upgrade),
        }
        # 占位要 finish 解锁前端；upgrade 只推 outline，避免再开一轮气泡
        ops = [OutboundOp(kind="outline", text=body, meta=meta)]
        if not upgrade:
            ops.append(
                OutboundOp(
                    kind="finish",
                    text="",
                    final=True,
                    meta={
                        "field": "finish",
                        "order": 1,
                        "source": "narrative_outline",
                        "slot": _OPENING_SLOT,
                        "placeholder": bool(placeholder),
                        "upgrade": False,
                    },
                )
            )
        request = OutboundRequest(
            session_id=sid,
            ops=tuple(ops),
            meta={
                "source": "narrative_outline",
                "slot": _OPENING_SLOT,
                "placeholder": bool(placeholder),
                "upgrade": bool(upgrade),
            },
        )
        self._execute_outbound_request(
            request,
            user_text="",
            background=True,
        )

    def _maybe_deliver_narrative_opening(self, session_id: str) -> None:
        """兼容旧入口：有正文则推送（占位已发出时走 upgrade）。"""
        sid = session_id.strip()
        if not sid or self._state_store is None:
            return
        state = self._state_store.session(sid)
        opening = self._resolve_narrative_outline_text(state)
        if not opening or opening == _OPENING_PLACEHOLDER:
            return
        upgrade = bool(state.director_cache.get("narrative_opening_placeholder_sent"))
        self._deliver_narrative_outline(
            sid,
            text=opening,
            upgrade=upgrade,
        )

    def _resolve_narrative_outline_text(self, state) -> str:
        """只认编剧写好的 opening。禁止用剧情 intent 现场拼「灯还亮着」。"""
        cached = str(state.director_cache.get("narrative_opening") or "").strip()
        if not cached or cached == _OPENING_PLACEHOLDER:
            return ""
        if bool(state.director_cache.get("narrative_opening_is_placeholder")):
            return ""
        return cached

    def note_agent_visible_speak(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str = "",
        agent_text: str = "",
    ) -> None:
        """角色可见开口落库：更新角色侧交互账本。

        用户与角色都开口才计一轮往来；满 3 轮或剧情 unit 总数超过 5 时
        导演与编剧一起醒，醒后清空往来计数。
        """
        from .responders.request_driven.character.interaction import (
            note_character_exchange,
            sync_dialogue_history_into_ledger,
        )

        sid = session_id.strip()
        if not sid or self._state_store is None:
            return
        state = self._state_store.session(sid)
        recent: tuple[str, ...] = ()
        dialogue_history = ""
        if self._snapshot_builder is not None:
            snap = self._snapshot_builder.build(sid, user_text=user_text)
            recent = tuple(snap.dialogue.recent_turns[-6:])
            dialogue_history = str(snap.dialogue.working_memory or "").strip()
        inbound = str(user_text or "").strip()
        note_character_exchange(
            state,
            user_text=inbound or str(state.last_real_user_text or ""),
            agent_text=agent_text,
        )
        sync_dialogue_history_into_ledger(
            state,
            dialogue_history=dialogue_history,
            recent_turns=recent,
        )
        state.last_agent_speak_at = time.time()
        if turn_index > 0:
            state.last_counted_speak_turn = int(turn_index)
        if inbound and str(agent_text or "").strip():
            state.interaction_exchange_count = int(
                getattr(state, "interaction_exchange_count", 0) or 0
            ) + 1
            coord = getattr(self, "_director_coordinator", None)
            if coord is not None:
                coord.maybe_wake_narrative(
                    sid,
                    inbound,
                    turn_index=turn_index,
                )

    def _pop_session_share_at(self, session_id: str, queue_index: int) -> bool:
        intent = self._session_manager.queues.share_queue.pop_at(session_id, queue_index)
        return intent is not None

    def _mark_recall_unit_consumed(self, session_id: str, unit_id: str) -> None:
        self._orchestrator.memory_warm_buffer(session_id).mark_unit_consumed(
            session_id,
            unit_id,
        )

    def _guidance_plot_brief(self, session_id: str) -> str:
        if self._state_store is None:
            return ""
        state = self._state_store.session(session_id)
        parts: list[str] = []
        plot_unit_id = ""
        flow = getattr(state, "plot_flow", None)
        if flow is not None and getattr(flow, "ready", False):
            text = " / ".join(
                p
                for p in (
                    str(getattr(flow, "focus_now", "") or "").strip(),
                    str(getattr(flow, "next_push", "") or "").strip(),
                )
                if p
            )
            if text:
                parts.append(text)
        arc = getattr(state, "plot_arc", None)
        if arc is not None and getattr(arc, "ready", False) and hasattr(arc, "active_unit"):
            active = arc.active_unit()
            if active is not None:
                plot_unit_id = str(getattr(active, "unit_id", "") or "").strip()
                intent = str(getattr(active, "intent", "") or "").strip()
                if intent and intent not in "\n".join(parts):
                    parts.append(intent)
        rhythm = getattr(state, "character_rhythm_schedule", None)
        entry = None
        if rhythm is not None and plot_unit_id and hasattr(rhythm, "unit_for_plot"):
            entry = rhythm.unit_for_plot(plot_unit_id)
        if entry is None and rhythm is not None:
            for item in list(getattr(rhythm, "executable_units", None) or []):
                if str(getattr(item, "status", "") or "") in ("pending", "reserved"):
                    entry = item
                    break
        if entry is not None and hasattr(entry, "render_enrichment"):
            enrich = str(entry.render_enrichment() or "").strip()
            if enrich:
                parts.append(enrich)
        return "\n".join(parts).strip()[:480]

    def _bind_orchestrator_runtime(self) -> None:
        hub = self._orchestrator.compose_queue_hub
        self._orchestrator.bind_memory_turn_gap(self._memory_turn_gap)
        self._orchestrator.bind_plot_brief(self._guidance_plot_brief)
        self._session_manager._compose_pending = hub.has_any_pending
        self._session_manager.queues.bind_compose_hub(hub)
        hub.bind_compose_scheduler(
            lambda session_id, mode: self._schedule_compose_prepare(session_id, mode=mode),
        )
        hub.bind_queue_decision_scheduler(self._schedule_queue_decision)
        self._queue_decision_runner.set_complete_handler(hub.on_queue_decision_complete)
        self._memory_compose._recall_pick_weights = self._orchestrator
        original_open = self._session_manager.open
        original_clear = self._session_manager.queues.clear_session
        original_rotate = self._session_manager._starter._on_rotate

        def _open(session_id: str, **kwargs):
            result = original_open(session_id, **kwargs)
            self._orchestrator.start_session_compose_sync(session_id)
            return result

        def _clear(session_id: str) -> None:
            sid = session_id.strip()
            self._orchestrator.clear_session_compose_state(sid)
            if self._turn_coordinator is not None:
                self._turn_coordinator.clear_session(sid)
            if self._orchestrator_thread is not None:
                self._orchestrator_thread.notify_session_close(sid)
            if self._state_store is not None:
                self._state_store.clear_session(sid)
            # rotate/reset 必须丢掉 compose 热态，否则 is_live_warm 会误判跳过进房 arm
            self._compose_manager_sessions.discard(sid)
            self._compose_manager_meta.pop(sid, None)
            self._compose_manager_materials.pop(sid, None)
            original_clear(sid)

        def _on_rotate(session_id: str) -> None:
            original_rotate(session_id)
            self._orchestrator.start_session_compose_sync(session_id)

        self._session_manager.holder.bind_on_reopen(self.bootstrap_proactive_loop)

        original_invalidate = self._compose_runner.invalidate

        def _invalidate_compose(session_id: str) -> None:
            original_invalidate(session_id)
            self._orchestrator.compose_director.invalidate_session(session_id)

        self._compose_runner.invalidate = _invalidate_compose  # type: ignore[method-assign]
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

    def _bind_compose_manager_sidechain(
        self,
        *,
        enabled: bool | None,
        config: ComposeManagerConfig | None,
    ) -> None:
        env_raw = os.environ.get("SPEAK_COMPOSE_MANAGER", "").strip().lower()
        if env_raw in {"0", "false", "no", "off"}:
            resolved_enabled = False
        elif env_raw in {"1", "true", "yes", "on"}:
            resolved_enabled = True
        elif enabled is None:
            resolved_enabled = False
        else:
            resolved_enabled = bool(enabled)
        base = config or ComposeManagerConfig()
        cfg = ComposeManagerConfig(
            enabled=resolved_enabled,
            compress_chunk_size=base.compress_chunk_size,
            staging_max_items=base.staging_max_items,
            staging_max_turn_age=base.staging_max_turn_age,
            staging_ttl_sec=base.staging_ttl_sec,
            stage_in_related_ratio=base.stage_in_related_ratio,
            retrieve_normal_ratio=base.retrieve_normal_ratio,
            bm25_min_score=base.bm25_min_score,
            bm25_top_k=base.bm25_top_k,
            stage_in_limit=base.stage_in_limit,
            history_query_turns=base.history_query_turns,
            rng_seed=base.rng_seed,
            director_memory_intervene_max=base.director_memory_intervene_max,
            director_bm25_top_k=base.director_bm25_top_k,
        )
        self._compose_memory_port = CallableMemorySearchPort(self._compose_manager_memory_search)
        self._compose_share_hint = PresenceShareHintPort(self._compose_manager_share_hint)
        self._compose_live_search_fn: (
            Callable[[str, str, int, MemoryHint], list[MemoryUnit]] | None
        ) = None
        manager = ComposeManager(
            cfg,
            memory_search=self._compose_memory_port,
            share_hint=self._compose_share_hint,
        )
        self._compose_gateway = ComposeManagerGateway(
            manager,
            on_fallback=lambda label, exc: logger.warning(
                "[compose_manager] fallback label=%s err=%s",
                label,
                exc,
            ),
        )
        self._speak_role = SpeakRole(generate_fn=self._role_generate)
        self._character_work = CharacterWorkGateway()
        self._character_agent: CharacterAgentHost | None = None
        self._character_runtime = CharacterRuntime(
            speak_role=self._speak_role,
            character_agent=None,
            request_helps=self._character_request_helps,
            pace_delivery=self._pace_delivery_plan_with_speak,
        )
        self._compose_manager_sessions: set[str] = set()
        self._compose_manager_meta: dict[str, dict[str, object]] = {}
        self._compose_manager_materials: dict[str, object] = {}
        from .responders.request_driven.orchestrator.blocks.memory.page_temp import (
            PageTempMemoryRing,
        )

        self._page_temp = PageTempMemoryRing(max_generations=2)

    def _character_request_helps(
        self,
        session_id: str,
        goals: tuple[str, ...],
        user_text: str,
    ) -> tuple[str, ...]:
        return self._character_work.request_helps(
            session_id=session_id,
            goals=goals,
            user_text=user_text,
            limit=1,
        )

    def attach_character_work_port(self, port: CharacterWorkPort) -> None:
        """挂载角色→worker 轻量工作口（io 分流；不向角色注入工具目录）。"""
        self._character_work.bind(port)

    def attach_compose_memory_search(
        self,
        search_fn: Callable[[str, str, int, MemoryHint], list[MemoryUnit]],
    ) -> None:
        """挂 Memory 实时检索到 ComposeManager staging 装入口。"""
        self._compose_live_search_fn = search_fn

    def attach_compose_embedder(self, embedder) -> None:
        """挂 embedding，供 buffer 内向量检索、导演 inject，以及编剧初始化场景种子近邻抽样。"""
        self._compose_gateway.manager.set_embedder(embedder)
        if getattr(self, "_screenwriter", None) is not None:
            self._screenwriter.set_embedder(embedder)
    def _compose_meta_for_snapshot(self, session_id: str) -> dict[str, object]:
        base = dict(self._orchestrator.compose_cache(session_id).meta_snapshot() or {})
        extra = self._compose_manager_meta.get(session_id.strip()) or {}
        if extra:
            base.update(extra)
        return base

    def _compose_manager_memory_search(
        self,
        session_id: str,
        query_text: str,
        limit: int,
        hint: MemoryHint,
    ) -> list[MemoryUnit]:
        """上游装入只用具体记忆条目；不把画像/人格/system 推进 staging。"""
        cap = max(1, int(limit))
        meta = self._orchestrator.compose_cache(session_id).meta_snapshot()
        # 明确忽略画像字段，避免噪声进临时记忆库
        _ = meta.get("interactor_portrait")
        _ = meta.get("guidance_persona")
        out: list[MemoryUnit] = []
        seen: set[str] = set()
        candidates = meta.get("guidance_recall_candidates") or []
        if isinstance(candidates, (list, tuple)) and candidates:
            for unit in units_from_recall_candidates(list(candidates), limit=cap):
                if unit.unit_id in seen:
                    continue
                seen.add(unit.unit_id)
                out.append(unit)
                if len(out) >= cap:
                    return out
        if self._compose_live_search_fn is not None and len(out) < cap:
            live = self._compose_live_search_fn(
                session_id,
                query_text,
                cap - len(out),
                hint,
            )
            for unit in live:
                if unit.unit_id in seen:
                    continue
                seen.add(unit.unit_id)
                out.append(unit)
                if len(out) >= cap:
                    break
        return out

    def _ingest_pull_into_compose_manager(
        self,
        session_id: str,
        similar: SimilarMemoryPullResult,
    ) -> None:
        """keyword/emergence pull 结果压入 ComposeManager staging，统一淘汰与检索。"""
        if not self._compose_gateway.enabled:
            return
        sid = session_id.strip()
        lines = (
            list(similar.social_prefetch_lines)
            + list(similar.warm_spread_lines)
            + list(similar.inject.lines)
        )
        unit_ids = (
            list(similar.social_prefetch_unit_ids)
            + list(similar.warm_spread_unit_ids)
            + list(similar.inject.unit_ids)
        )
        units: list[MemoryUnit] = []
        seen: set[str] = set()
        for line, uid in zip(lines, unit_ids):
            text = str(line or "").strip()
            unit_id = str(uid or "").strip()
            if not text or not unit_id or unit_id in seen:
                continue
            seen.add(unit_id)
            units.append(
                MemoryUnit(unit_id=unit_id, text=text, source="memory_pull"),
            )
        if not units:
            return
        self._ensure_compose_manager_session(sid, "")
        self._compose_gateway.manager.ingest_units(sid, units, kind="memory_pull")

    def _deferred_share_texts(self, session_id: str, *, limit: int | None = None) -> list[str]:
        intents = self._session_manager.deferred_share_intents(session_id)
        items = list(intents[:limit] if limit is not None else intents)
        return [
            topic
            for item in items
            if (topic := str(getattr(item, "topic", "") or "").strip())
        ]

    def _collect_share_texts_for_dynamic(self, session_id: str) -> list[str]:
        """合并 session 延迟分享 + presence 待分享队列，供编剧写入剧情流调度。"""
        texts: list[str] = []
        seen: set[str] = set()

        def _add(raw: str) -> None:
            text = str(raw or "").strip()
            if not text or text in seen:
                return
            seen.add(text)
            texts.append(text)

        for topic in self._deferred_share_texts(session_id):
            _add(topic)
        share_state = self._orchestrator.share_compose_state(session_id)
        for event in share_state.events:
            _add(getattr(event, "topic", "") or getattr(event, "brief", ""))
        summary = str(share_state.summary or "").strip()
        if summary:
            _add(summary[:240])
        return texts

    def _compose_manager_share_hint(self, session_id: str) -> str:
        # init 80% share 相关：只用分享意图正文，不用 planner/persona 预览壳
        texts = self._collect_share_texts_for_dynamic(session_id)[:3]
        return " ".join(texts)

    def _role_generate(self, system: str, user_text: str) -> str:
        return self._llm.generate(user_text, system=system).text

    def _ensure_compose_manager_session(self, session_id: str, user_text: str) -> None:
        if not self._compose_gateway.enabled:
            return
        sid = session_id.strip()
        if sid in self._compose_manager_sessions:
            return
        self._compose_gateway.manager.init_session(sid, query_text=user_text)
        self._compose_manager_sessions.add(sid)

    def _refresh_compose_manager_director_meta(self, session_id: str, user_text: str) -> None:
        if not self._compose_gateway.enabled:
            return
        sid = session_id.strip()
        self._ensure_compose_manager_session(sid, user_text)
        self._compose_gateway.manager.on_user_ingress(sid, user_text)
        materials = self._compose_gateway.manager.export_dynamic_materials(
            sid,
            user_text=user_text,
            share_texts=self._collect_share_texts_for_dynamic(sid),
        )
        view = self._compose_gateway.context_for_director_or_empty(sid, user_text=user_text)
        self._compose_manager_meta[sid] = {
            "compose_manager_director_brief": view.brief,
            "compose_manager_memory_brief": view.memory_brief,
            "compose_manager_history_brief": view.history_brief,
            "compose_manager_director_memory_texts": list(view.director_memory_texts),
            "compose_manager_director_memory_ids": list(view.director_memory_ids),
            "compose_manager_role_memory_texts": list(view.role_memory_texts),
            "compose_manager_role_memory_ids": list(view.role_memory_ids),
            "intervene_max": int(view.meta.get("intervene_max", 1) or 1),
            "role_hits_visible": True,
            # 动态层库存：供编剧写入剧情流调度；导演不得挑选压入角色
            "dynamic_memory_ids": list(materials.memory_ids),
            "dynamic_memory_texts": list(materials.memory_texts),
            "dynamic_share_texts": list(materials.share_texts),
            "dynamic_share_consumption_history": (
                self._session_manager.queues.share_queue.consumption_history(sid)
            ),
            "dynamic_layer_scheduler": "screenwriter_plot_flow",
        }
        self._compose_manager_materials[sid] = materials

    def _director_dynamic_schedule(self, session_id: str):
        """从剧情流读取编剧写入的记忆/分享调度（导演不得代决）。"""
        from agent.soul.speak.responders.request_driven.composer.projectors.dynamic_layer import (
            DynamicLayerSchedule,
        )

        sid = session_id.strip()
        state = self._state_store.session(sid)
        flow = state.plot_flow
        if flow is None or not getattr(flow, "ready", False):
            # 场记未就绪时仍可读材料调度字段
            if flow is None:
                return DynamicLayerSchedule(reason="missing_plot_flow", source="screenwriter")
        return DynamicLayerSchedule(
            inject_memory=bool(getattr(flow, "inject_memory", False)),
            memory_unit_ids=tuple(
                str(x) for x in (getattr(flow, "memory_unit_ids", None) or []) if str(x).strip()
            ),
            inject_share=bool(getattr(flow, "inject_share", False)),
            share_indices=tuple(
                int(x)
                for x in (getattr(flow, "share_indices", None) or [])
                if str(x).lstrip("-").isdigit()
            ),
            pass_info=bool(getattr(flow, "pass_info", False)),
            reason=str(getattr(flow, "material_reason", "") or "screenwriter_plot_flow"),
            source="screenwriter",
        )

    def _bind_director_system(self) -> None:
        queues = self._session_manager.queues
        self._snapshot_port = RegistrySessionSnapshotPort(
            self.session_registry,
            self._session_manager,
            context_distiller=self._context,
            delivery_progress_fn=lambda sid: (
                self._delivery_executor.progress(sid)
                if self._delivery_executor is not None
                else (0, 0)
            ),
        )
        self._orchestrator.bind_session_port(self._snapshot_port)
        self._snapshot_builder = SnapshotBuilder(
            self._snapshot_port,
            state_store=self._state_store,
            compose_meta_fn=self._compose_meta_for_snapshot,
        )
        self._director_agent_host: DirectorAgentHost | None = None
        self._character_agent = CharacterAgentHost(
            self._llm.llm,
            generate_fn=self._role_generate,
            name="speak-character",
            auto_start=self._llm.llm is not None,
        )
        self._character_runtime.bind_character_agent(self._character_agent)
        if self._director_llm.available:
            from .responders.request_driven.composer.ports.buffer_tools import (
                MemoryBufferActionRunner,
            )

            self._director_llm_caller = DirectorLLMCaller(llm=self._director_llm._engine.llm)
            memory_runner = MemoryBufferActionRunner(self._compose_gateway.manager)
            self._director_agent_host = DirectorAgentHost(
                self._director_llm._engine.llm,
                action_runner=memory_runner,
                name="speak-director",
                auto_start=True,
            )
        self._screenwriter = Screenwriter(
            llm=self._director_llm_caller,
            on_opening_ready=self._on_screenwriter_opening_ready,
        )
        self._director_coordinator = DirectorCoordinator(
            state_store=self._state_store,
            snapshot_builder=self._snapshot_builder,
            llm=self._director_llm_caller,
            orchestrator=self._orchestrator,
            share_wants_fn=self._director_share_wants,
            silence_armed_fn=self._director_silence_armed,
            social_armed_fn=self._director_social_armed,
            director_agent=self._director_agent_host,
            materials_refresh_fn=self._refresh_compose_manager_director_meta,
            screenwriter=self._screenwriter,
            peek_user_pending_fn=lambda sid: self._session_manager.user_queue.has_pending(sid),
            is_turn_busy_fn=self._session_manager.is_turn_busy,
            is_pushing_fn=self._session_manager.is_pushing,
        )
        self._orchestrator_thread = OrchestratorThread(
            state_store=self._state_store,
            coordinator=self._director_coordinator,
            on_delivery_ready=self._on_async_delivery_ready,
            on_character_handoff=self._on_director_character_handoff,
        )
        self._session_ingress = SessionOrchestratorIngress(self._orchestrator_thread)
        self._delivery_executor = DeliveryExecutor(
            emit_fn=self._stream._emit,
            on_segment_progress=lambda sid, idx, total: None,
            on_done=lambda sid: self._orchestrator_thread.notify_delivery_done(sid),
        )
        queues.bind_typing_start(self._on_typing_start_for_directors)
        queues.bind_typing_idle(self._on_typing_idle_for_directors)

    def _nudge_after_opening_ready(self, session_id: str) -> None:
        """开场旁白就绪：往来水位标到当前 unit，轮询回到第一阶，并补一次导演初始化。"""
        from .responders.request_driven.orchestrator.state.core.interaction_plan import (
            reset_narrative_wake_counters,
        )

        sid = session_id.strip()
        if not sid or self._state_store is None:
            return
        state = self._state_store.session(sid)
        reset_narrative_wake_counters(state)
        idle = self._state_store.poll_frame_manager(sid, "idle")
        idle.reset_decay()
        idle.schedule_next(advance=False)
        coord = getattr(self, "_director_coordinator", None)
        if coord is None:
            return

        def _run() -> None:
            coord.ensure_director_init(sid)
            frame = self._state_store.poll_frame_manager(sid, "idle")
            frame.reset_decay()
            frame.schedule_next(advance=False)

        threading.Thread(
            target=_run,
            daemon=True,
            name=f"director-init-{sid[:16]}",
        ).start()

    def _on_screenwriter_opening_ready(self, session_id: str, opening: str) -> None:
        """编剧 Agent 后台写完 opening 后推送升级（占位 → 正文）。"""
        sid = str(session_id or "").strip()
        body = str(opening or "").strip()
        if not sid or not body or body == _OPENING_PLACEHOLDER:
            return
        upgrade = True
        if self._state_store is not None:
            state = self._state_store.session(sid)
            upgrade = bool(state.director_cache.get("narrative_opening_placeholder_sent"))
        self._deliver_narrative_outline(sid, text=body, upgrade=upgrade)

    def _director_share_wants(self, session_id: str) -> bool:
        share_state = self._orchestrator.share_compose_state(session_id)
        return bool(share_state.wants_share)

    def _director_silence_armed(self, session_id: str) -> bool:
        del session_id
        return False

    def _director_social_armed(self, session_id: str) -> str | None:
        sid = session_id.strip()
        if sid in self._session_manager.social.enter_greeting._armed:
            return "enter_greeting"
        return None

    def _on_typing_start_for_directors(self, session_id: str) -> None:
        # 用户开始输入：暂停 idle 轮询，等 idle 后再按衰减重启
        if self._orchestrator_thread is None:
            return
        frame_mgr = self._orchestrator_thread._state_store.poll_frame_manager(
            session_id, "idle"
        )
        frame_mgr.armed = False

    def _on_typing_idle_for_directors(self, session_id: str) -> None:
        if self._orchestrator_thread is None:
            return
        sid = session_id.strip()
        runtime = self._session_manager.queues._runtime(sid)
        runtime.typing_idle_handoff.set()
        # 输入停顿后恢复 idle：同阶重约，不升梯、不重置用户周期
        frame_mgr = self._orchestrator_thread._state_store.poll_frame_manager(
            sid, "idle"
        )
        frame_mgr.schedule_next(advance=False)

    def _on_async_delivery_ready(self, session_id: str, trigger: str) -> None:
        # 占位导演文案禁止直推；可见正文只经角色交接（_on_director_character_handoff）
        del session_id, trigger

    def _on_director_character_handoff(
        self,
        session_id: str,
        handoff: dict[str, Any],
    ) -> None:
        """导演主动开口：请求角色生成；不得占用用户角色 turn_busy。

        权限边界：
        - 导演无权阻塞角色用户接口；用户 turn / 用户队列优先。
        - 用户已入站或用户角色正在开口时，本拍主动 handoff 直接丢弃（不 defer 挡路）。
        - 仅在「非用户占用」的出站推送中才短暂 defer，等推送结束后再取。
        """
        sid = session_id.strip()
        if not sid or not handoff:
            return
        self._record_agent_delivery_trace(
            sid,
            trigger_id=str(handoff.get("trigger_id") or ""),
            status="generating",
        )
        state = self._state_store.session(sid)
        if self._director_must_yield_to_user(sid):
            # 用户优先：不把 handoff 塞回 pending，避免再次挡角色
            self._abort_proactive_handoff(
                sid,
                None,
                executable_unit_id=str(handoff.get("executable_unit_id") or "").strip(),
                reason="dropped_user_priority",
                rearm=False,
            )
            get_prompt_trace().emit_event(
                sid,
                label="character_handoff_dropped_user_priority",
                turn_index=int(handoff.get("turn_index") or 0),
                payload=dict(handoff),
            )
            return
        if self._session_manager.is_pushing(sid):
            # 非用户打断的出站：可 defer；用户打断则上面已 yield
            state.pending_character_handoff = dict(handoff)
            get_prompt_trace().emit_event(
                sid,
                label="character_handoff_deferred_pushing",
                turn_index=int(handoff.get("turn_index") or 0),
                payload=dict(handoff),
            )
            return
        with self._character_handoff_guard:
            if sid in self._character_handoff_inflight:
                state.pending_character_handoff = dict(handoff)
                return
            self._character_handoff_inflight.add(sid)

        def _run() -> None:
            try:
                self._execute_character_handoff(sid, dict(handoff))
            finally:
                with self._character_handoff_guard:
                    self._character_handoff_inflight.discard(sid)
                exec_id = str(handoff.get("executable_unit_id") or "").strip()
                if exec_id:
                    leftover = self._state_store.session(sid).character_rhythm_schedule
                    still_reserved = any(
                        e.unit_id == exec_id and e.status == "reserved"
                        for e in leftover.executable_units
                    )
                    if still_reserved:
                        self._abort_proactive_handoff(
                            sid,
                            None,
                            executable_unit_id=exec_id,
                            reason="handoff_thread_leftover_reserved",
                        )
                if (
                    self._orchestrator_thread is not None
                    and self._director_coordinator is not None
                    and self._director_coordinator.peek_character_handoff(sid) is not None
                    and not self._director_must_yield_to_user(sid)
                    and not self._session_manager.is_pushing(sid)
                ):
                    self._orchestrator_thread._maybe_notify_character_handoff(sid)

        threading.Thread(
            target=_run,
            name=f"speak-character-handoff-{sid[:16]}",
            daemon=True,
        ).start()

    def _director_must_yield_to_user(self, session_id: str) -> bool:
        """用户入站 / 用户角色 turn 优先于导演主动开口。"""
        sid = session_id.strip()
        if not sid:
            return False
        if self._session_manager.has_user_interrupt(sid):
            return True
        if self._session_manager.user_queue.has_pending(sid):
            return True
        if self._session_manager.is_turn_busy(sid):
            return True
        return False

    def _record_agent_delivery_trace(
        self,
        session_id: str,
        *,
        trigger_id: str,
        status: str,
        text: str = "",
    ) -> None:
        state = self._state_store.session(session_id)
        entries = list(state.director_cache.get("agent_delivery_trace") or [])
        normalized_trigger = trigger_id.strip()
        entry = {
            "trigger_id": normalized_trigger,
            "status": status.strip(),
            "text": text.strip(),
        }
        for index in range(len(entries) - 1, -1, -1):
            prior = entries[index]
            if (
                isinstance(prior, dict)
                and str(prior.get("trigger_id") or "").strip() == normalized_trigger
            ):
                entries[index] = entry
                break
        else:
            entries.append(entry)
        state.director_cache["agent_delivery_trace"] = entries[-12:]

    def _abort_proactive_handoff(
        self,
        session_id: str,
        request: Any,
        *,
        reason: str,
        executable_unit_id: str = "",
        rearm: bool = True,
    ) -> None:
        """交接失败：把 reserved 放回 pending，避免预约再也叫不醒角色。"""
        sid = session_id.strip()
        state = self._state_store.session(sid)
        exec_id = str(
            executable_unit_id
            or getattr(request, "executable_unit_id", "")
            or ""
        ).strip()
        if exec_id:
            state.character_rhythm_schedule.release_reserved(exec_id)
            state.director_cache["character_rhythm_schedule"] = (
                state.character_rhythm_schedule.snapshot()
            )
        trigger = str(getattr(request, "trigger_id", "") or "").strip()
        state.notes.append(f"character_handoff: abort {reason} trigger={trigger}")
        logger.info(
            "[character_handoff] abort session=%s reason=%s origin=%s exec=%s",
            sid,
            reason,
            getattr(request, "origin", ""),
            exec_id,
        )
        if rearm and self._director_coordinator is not None:
            self._director_coordinator.on_delivery_done(sid)

    def _execute_character_handoff(
        self,
        session_id: str,
        handoff: dict[str, Any],
    ) -> None:
        """导演主动：请求角色开口。不占用 turn_busy（用户角色接口不可被导演阻塞）。

        产出中若发现用户入站：立刻停，把话筒交给用户热路径；导演稍后再请求交互记录重决策。
        """
        if self._director_coordinator is None:
            return
        sid = session_id.strip()
        from .responders.request_driven.character import CharacterReplyRequest

        payload = dict(handoff)
        request = CharacterReplyRequest.from_dict({**payload, "session_id": sid})
        if request is None or request.origin not in ("director", "booked"):
            self._abort_proactive_handoff(
                sid,
                request,
                executable_unit_id=str(payload.get("executable_unit_id") or "").strip(),
                reason="origin_not_proactive",
            )
            return
        state = self._state_store.session(sid)
        if self._director_must_yield_to_user(sid) or (
            float(request.created_at or 0.0) < float(state.last_user_speak_at or 0.0)
        ):
            self._abort_proactive_handoff(
                sid,
                request,
                reason="yield_to_user",
                rearm=False,
            )
            return
        if (
            request.trigger_id
            and state.last_character_trigger_id
            and request.trigger_id == state.last_character_trigger_id
        ):
            self._abort_proactive_handoff(
                sid,
                request,
                reason="duplicate_trigger",
            )
            get_prompt_trace().emit_event(
                sid,
                label="character_handoff_duplicate_trigger",
                turn_index=request.turn_index,
                payload={"trigger_id": request.trigger_id},
            )
            return

        user_text = request.effective_user_text
        if request.origin in ("director", "booked") and not request.director_cue:
            request.director_cue = "（系统：导演预约开口，用户仍沉默。）"
        if request.origin not in ("director", "booked") and not user_text:
            self._abort_proactive_handoff(
                sid,
                request,
                reason="empty_user_text",
            )
            return
        logger.info(
            "[character_handoff] start session=%s origin=%s reason=%s exec=%s",
            sid,
            request.origin,
            request.reason,
            request.executable_unit_id,
        )
        if self._session_manager.is_pushing(sid):
            if self._director_must_yield_to_user(sid):
                self._abort_proactive_handoff(
                    sid,
                    request,
                    reason="skip_push_user_priority",
                    rearm=False,
                )
                return
            state.pending_character_handoff = request.to_dict()
            return

        turn_index = int(request.turn_index or 0)
        if turn_index <= 0:
            turn_index = self.session_registry.current_turn_index(sid) + 1
            request.turn_index = turn_index

        # 故意不 begin_turn_busy：导演主动不得锁住用户→角色热路径
        self._record_agent_delivery_trace(
            sid,
            trigger_id=request.trigger_id,
            status="generating",
        )
        get_prompt_trace().emit_event(
            sid,
            label="character_handoff_start",
            turn_index=turn_index,
            payload=request.to_dict(),
        )
        notes: list[str] = [
            "character_handoff",
            request.reason,
            f"trigger={request.trigger_id}",
            "director_no_turn_busy",
        ]
        poll_silence = request.origin in ("director", "booked")
        try:
            if self._director_must_yield_to_user(sid):
                notes.append("character_handoff: abort_before_generate_user_ingress")
                self._abort_proactive_handoff(
                    sid,
                    request,
                    reason="abort_before_generate_user_ingress",
                    rearm=False,
                )
                return
            self._refresh_compose_manager_director_meta(sid, user_text)
            state = self._state_store.session(sid)
            director_plan = state.pending_delivery_plan or state.delivery_plan
            if director_plan is None or director_plan.is_empty:
                from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
                    ReplySegment,
                    build_delivery_plan,
                )

                director_plan = build_delivery_plan(
                    segments=[ReplySegment(text="…", wait_ms=120, continuity="finish")],
                    continuity="finish",
                    plan_id=f"handoff-{sid}-{turn_index}",
                    turn_index=turn_index,
                )
            bundle = self._compose_bundle(
                sid,
                user_text,
                mode="proactive",
                turn_index=turn_index,
            )
            if self._director_must_yield_to_user(sid) or (
                float(request.created_at or 0.0)
                < float(self._state_store.session(sid).last_user_speak_at or 0.0)
            ):
                notes.append("character_handoff: abort_before_role_user_ingress")
                self._record_agent_delivery_trace(
                    sid,
                    trigger_id=request.trigger_id,
                    status="aborted_user_ingress",
                )
                self._abort_proactive_handoff(
                    sid,
                    request,
                    reason="abort_before_role_user_ingress",
                    rearm=False,
                )
                return
            answer_text, parsed, paced, used_role, role_timeline = (
                self._run_booked_character_reply(
                    request=request,
                    bundle=bundle,
                    notes=notes,
                    director_plan=director_plan,
                )
            )
            state.last_character_trigger_id = request.trigger_id
            if self._director_must_yield_to_user(sid) or (
                float(request.created_at or 0.0)
                < float(self._state_store.session(sid).last_user_speak_at or 0.0)
            ):
                notes.append("character_handoff: abort_after_role_user_ingress")
                self._record_agent_delivery_trace(
                    sid,
                    trigger_id=request.trigger_id,
                    status="aborted_user_ingress",
                )
                self._abort_proactive_handoff(
                    sid,
                    request,
                    reason="abort_after_role_user_ingress",
                    rearm=False,
                )
                return
            if paced.is_empty and not answer_text.strip() and role_timeline is None:
                self._record_agent_delivery_trace(
                    sid,
                    trigger_id=request.trigger_id,
                    status="released",
                )
                if request.executable_unit_id:
                    state.character_rhythm_schedule.release_reserved(
                        request.executable_unit_id
                    )
                    state.director_cache["character_rhythm_schedule"] = (
                        state.character_rhythm_schedule.snapshot()
                    )
                get_prompt_trace().emit_event(
                    sid,
                    label="character_handoff_empty",
                    turn_index=turn_index,
                    payload={"notes": notes, "parsed": parsed.to_dict()},
                )
                return

            self._state_store.set_delivery_plan(sid, paced)
            state.pending_delivery_plan = None
            events: list = []
            answer = "\n".join(
                segment.text for segment in paced.segments if segment.text.strip()
            )
            if not answer.strip() and answer_text.strip():
                answer = answer_text.strip()
            live_stream = self._has_live_stream_session(sid)
            if live_stream:
                self._record_agent_delivery_trace(
                    sid,
                    trigger_id=request.trigger_id,
                    status="delivering",
                    text=answer,
                )
                if used_role and role_timeline is not None:
                    events = self._deliver_role_timeline(
                        sid,
                        role_timeline,
                        user_text=user_text,
                        background=True,
                    )
                else:
                    notes.append("character_handoff: skipped_non_role_outbound")
                self._record_agent_delivery_trace(
                    sid,
                    trigger_id=request.trigger_id,
                    status="queued_for_delivery",
                    text=answer,
                )
            else:
                from agent.soul.speak.io.outbound.channel_ids import normalize_channel_id

                channel_id = normalize_channel_id(
                    self.session_registry.get_bound_interactor(sid) or "",
                    sid,
                )
                if channel_id and answer.strip():
                    self.enqueue_agent_outbound(
                        {
                            "session_id": sid,
                            "channel_id": channel_id,
                            "message": answer,
                            "agent_initiated": True,
                            "create_window": True,
                            "source": "character_handoff",
                            "proactive_intent_id": str(
                                request.executable_unit_id
                                or request.trigger_id
                                or request.reason
                                or f"handoff-{sid}-{turn_index}"
                            ),
                        }
                    )
                    self._record_agent_delivery_trace(
                        sid,
                        trigger_id=request.trigger_id,
                        status="queued_offline",
                        text=answer,
                    )
                else:
                    self._record_agent_delivery_trace(
                        sid,
                        trigger_id=request.trigger_id,
                        status="released",
                        text=answer,
                    )
            if answer.strip():
                last_fp = state.character_rhythm_schedule.last_answer_fingerprint()
                same_answer = bool(last_fp) and last_fp == answer.strip()[:120]
                self._commit_delivery_step(
                    session_id=sid,
                    request=request,
                    answer_text=answer,
                    chose_silence=False,
                )
                if not same_answer:
                    self._session_manager.begin_turn(sid)
                    self.record_dialogue(sid, user_text, answer)
                    self.note_agent_visible_speak(
                        sid,
                        turn_index=turn_index,
                        user_text=user_text,
                        agent_text=answer,
                    )
                    session_state = paced.continuity
                    if parsed is not None:
                        session_state = parsed.session_state or paced.continuity
                    self._on_compose_turn_complete(
                        sid,
                        user_text,
                        answer,
                        turn_index,
                        session_state,
                    )
                    self._session_manager.on_turn_complete(
                        sid,
                        mode="inbound",
                        session_state=session_state,
                        answer=answer,
                    )
                else:
                    state.notes.append("character_handoff: skip_duplicate_wm")
            # poll 沉默 handoff 不碰真实用户队列；有用户入队时交给用户热路径直达角色
            get_prompt_trace().emit_event(
                sid,
                label="character_handoff_done",
                turn_index=turn_index,
                payload={
                    "answer": answer,
                    "stream_event_count": len(events),
                    "notes": notes,
                    "poll_silence": poll_silence,
                    "trigger_id": request.trigger_id,
                    "user_queue_pending": self._session_manager.user_queue.has_pending(sid),
                },
            )
        finally:
            # 确保 handoff 路径也会续 poll（outbound on_done 若未触发则补一次）
            if self._orchestrator_thread is not None:
                idle = self._state_store.poll_frame_manager(sid, "idle")
                if not idle.armed:
                    self._orchestrator_thread.notify_delivery_done(sid)

    def _drain_async_delivery_queue(self, *, max_items: int = 4) -> None:
        # 同步出站路径已接管；清空遗留队列，避免重启后误推占位文案
        with self._async_ready_guard:
            self._async_ready_sessions.clear()

    def _execute_async_delivery_for_session(self, session_id: str) -> None:
        return

    def flush_async_delivery(self, session_id: str) -> None:
        return

    def is_busy(self, session_id: str) -> bool:
        return self._session_manager.is_busy(session_id)

    def notify_director_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int | None = None,
    ) -> dict[str, Any]:
        """旁路通知导演写表/清静默（仅供下一拍排程）。角色正文不经此路径。"""
        sid = session_id.strip()
        text = user_text.strip()
        if not sid or not text:
            return {"notified": False, "reason": "empty"}
        if self._session_ingress is None:
            return {"notified": False, "reason": "ingress_unbound"}
        idx = (
            int(turn_index)
            if turn_index is not None
            else self.session_registry.current_turn_index(sid) + 1
        )
        self._refresh_compose_manager_director_meta(sid, text)
        self._session_ingress.notify_user_input(sid, text, turn_index=idx)
        return {
            "notified": True,
            "turn_index": idx,
            "busy": self.is_busy(sid),
        }

    def stamp_user_ingress(self, session_id: str, user_text: str) -> None:
        """用户原文落地：清静默、撤销导演主动 handoff；不跑导演 LLM。

        最新原话写入角色侧交互账本；编剧/导演稍后向角色请求，不阻塞热路径。
        导演无权阻塞角色接口：此处直接撤掉 pending handoff，让用户 turn 独占角色。
        """
        from .responders.request_driven.character.interaction import note_pending_user

        sid = session_id.strip()
        text = user_text.strip()
        if not sid or not text:
            return
        state = self._state_store.session(sid)
        note_pending_user(state, user_text=text)
        state.silence_log.clear()
        state.director_cache.pop("user_silence", None)
        state.pending_character_handoff = None
        state.narrative_card.interaction_mode = "user_utterance"
        state.narrative_card.user_activity = "正在与你文字往来"
        state.notes.append("ingress: user_direct_to_character")
        state.notes.append("ingress: director_handoff_cleared_for_user_priority")
        if self._session_manager.is_pushing(sid):
            self._session_manager.end_push(sid)
            state.notes.append("ingress: outbound_push_released_for_user")

    def _wait_session_idle(self, session_id: str, *, timeout_sec: float = 45.0) -> bool:
        deadline = time.time() + max(0.0, float(timeout_sec))
        while time.time() < deadline:
            if not self.is_busy(session_id):
                return True
            time.sleep(0.05)
        return not self.is_busy(session_id)

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

    def _on_compose_turn_complete(
        self,
        session_id: str,
        user_text: str,
        agent_text: str,
        turn_index: int,
        session_state: str,
    ) -> None:
        if self._compose_gateway.enabled:
            self._compose_gateway.manager.on_turn_complete(
                session_id,
                user_text,
                agent_text,
            )
        self._guidance_control.on_turn_complete(
            session_id,
            session_state=session_state,
        )
        if self._turn_coordinator is None:
            return
        director = self._orchestrator.compose_director
        plan = self._turn_coordinator.plan_for_turn(session_id, turn_index)
        if plan is None:
            plan = director.load_plan(session_id, turn_index)
        presence = self._presence
        if plan is not None:
            notes = director.consume_emits(
                plan,
                pop_presence_share_at=(
                    presence.consume_share_at if presence is not None else None
                ),
                pop_session_share_at=self._pop_session_share_at,
                use_session_share_queue=self._orchestrator.uses_session_share_queue(
                    session_id,
                ),
                mark_recall_unit_consumed=self._mark_recall_unit_consumed,
            )
            plan.notes.extend(notes)
        if session_state == "finish":
            self._memory_compose.refresh_similar_memories_after_turn(
                session_id,
                turn_index=turn_index + 1,
                user_text=user_text,
                agent_text=agent_text,
            )
        record = self.session_registry.get(session_id)
        self._compose_runner.schedule_director_build(
            self._orchestrator,
            director,
            session_id,
            target_turn_index=turn_index + 1,
            user_text=user_text,
            generation=record.generation,
            agent_text=agent_text,
        )

    def _kick_for_upcoming_turn(
        self,
        session_id: str,
        user_text: str,
        turn_index: int,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> None:
        if self._turn_coordinator is None:
            return
        record = self.session_registry.get(session_id)
        self._turn_coordinator.kick_on_user_input(
            session_id,
            user_text,
            turn_index=turn_index,
            memory_compose=self._memory_compose,
            generation=record.generation,
            mode=mode,
        )

    def _before_compose_bundle(self, session_id: str, user_text: str) -> None:
        # 用户热路径禁止 wait 导演 compose；plan_control_arc 只异步 warm
        del user_text
        return

    def _bind_orchestrator_interactor_portrait(self) -> None:
        self._orchestrator.bind_interactor_portrait_bridge(
            self._memory_compose,
            portrait_wait_ms=self._portrait_wait_ms,
        )

    def _apply_compose_context(
        self,
        bundle,
        *,
        similar,
        portrait,
    ) -> None:
        self._memory_compose.apply_similar_memories(bundle, similar)
        self._ingest_pull_into_compose_manager(bundle.session_id, similar)
        from .responders.request_driven.orchestrator.blocks.persona import (
            interactor_pull_from_memory_result,
        )

        pulled = interactor_pull_from_memory_result(portrait)
        self._orchestrator.interactor_portrait.apply_to_bundle(bundle, pulled)

    def _refresh_interactor_portrait_on_bundle(
        self,
        session_id: str,
        bundle,
        turn_index: int,
    ) -> None:
        pulled = self._orchestrator.interactor_portrait.pull_for_compose(
            session_id,
            turn_index,
        )
        if pulled.portrait_text.strip() or pulled.display_name.strip():
            self._orchestrator.interactor_portrait.apply_to_bundle(bundle, pulled)

    def _bundle_from_director_plan(
        self,
        director_plan,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode,
    ):
        if director_plan is None:
            return None
        frame = director_plan.prepared_frame
        if frame is None:
            return None
        bundle = self._orchestrator.finalize(frame, user_text, session_id=session_id)
        bundle.meta["compose_source"] = "director_plan"
        return bundle

    def _finish_turn_bundle(
        self,
        bundle: SpeakPromptBundle,
        session_id: str,
        user_text: str,
        *,
        mode: SpeakTurnMode,
        turn_index: int,
        similar,
        portrait,
        director_plan=None,
    ) -> SpeakPromptBundle:
        if director_plan is None:
            raise RuntimeError("speak compose requires director_plan")
        record = self.session_registry.get(session_id)
        presence = self._presence
        ctx = self._orchestrator.pipeline_context(
            session_id=session_id,
            turn_index=turn_index,
            user_text=user_text,
            generation=record.generation,
            mode=mode,
            social=self._session_manager.social,
            story_port=self._story_port,
            world_id_fn=self._world_id_fn,
            memory_compose=self._memory_compose,
            similar=similar,
            portrait=portrait,
            pop_presence_share_at=(
                presence.consume_share_at
                if presence is not None
                else None
            ),
            pop_session_share_at=self._pop_session_share_at,
            mark_recall_unit_consumed=self._mark_recall_unit_consumed,
        )
        finished = self._orchestrator.compose_director.finish_turn(
            director_plan,
            bundle,
            ctx,
        )
        if self._turn_coordinator is not None:
            finished.meta["turn_coordinator"] = self._turn_coordinator.state(
                session_id,
            ).snapshot()
            finished.meta["director_refresh"] = finished.meta["turn_coordinator"].get(
                "refresh",
            )
        finished.meta["session_typing"] = self._session_manager.queues._runtime(
            session_id,
        ).snapshot_typing()
        brew_queue = self._session_manager.queues.brew_queue_snapshot(session_id)
        finished.meta["session_brew_queue"] = brew_queue
        brew_lines = brew_queue.get("lines") if isinstance(brew_queue, dict) else None
        if isinstance(brew_lines, list) and brew_lines:
            finished.meta["recent_brew_lines"] = "\n".join(
                str(line).strip() for line in brew_lines if str(line).strip()
            )
        get_prompt_trace().emit_compose(
            session_id,
            turn_index=turn_index,
            bundle=finished,
            cache=self.session_trace_cache(session_id, turn_index=turn_index),
        )
        return finished

    def _execute_enter_greeting(self, spec) -> None:
        from .responders.request_driven.orchestrator.blocks.guidance.session_bridge import (
            resolve_enter_greeting_user_text,
        )
        from .session.manage.types import EnterGreetingTurnSpec

        assert isinstance(spec, EnterGreetingTurnSpec)
        session_id = spec.session_id.strip()
        if not session_id:
            return
        # Speak 独立运转：无前端连接也执行问候；事件经 outbound bus 缓冲，适配器随时可挂接冲刷
        if self._session_manager.is_pushing(session_id):
            logger.info(
                "[Speak] enter_greeting skipped: pushing session_id=%s",
                session_id,
            )
            return
        if self._session_manager.user_queue.has_pending(session_id):
            logger.info(
                "[Speak] enter_greeting skipped: pending user queue session_id=%s",
                session_id,
            )
            return
        # angle/thought 只进 social guidance，由主回复 LLM 生成可见话头；
        # 不再 brew 内部决策文案（否则会把「角度」直接当消息推到前端）。
        self._session_manager.social.arm_enter_greeting(spec)
        logger.info(
            "[Speak] enter_greeting fire session_id=%s elapsed=%.1fs live=%s",
            session_id,
            float(spec.elapsed_sec),
            self._has_live_stream_session(session_id),
        )
        self.run_turn(
            session_id,
            resolve_enter_greeting_user_text(spec),
            stream=True,
            mode="proactive",
            record=True,
        )

    def arm_enter_greeting(self, session_id: str) -> None:
        """进房：先挂 poll/节奏（立刻），编剧开场后台跑（不堵事件循环）。"""
        sid = session_id.strip()
        # 先挂生命线，避免等编剧 Agent 多步 LLM 把整条 Speak 热路径冻住
        self.bootstrap_proactive_loop(sid)
        self._session_manager.social.enter_greeting.arm_session(sid)
        self._schedule_compose_prepare(sid, mode="proactive")
        self._schedule_screenwriter_init(sid)

    def bootstrap_proactive_loop(self, session_id: str) -> None:
        """恢复生命线扫描；每个 generation 只预置一次节奏开口阶梯。"""
        sid = session_id.strip()
        if not sid or self._state_store is None:
            return
        if self._orchestrator_thread is not None:
            self._orchestrator_thread.activate_session(sid)
        idle = self._state_store.poll_frame_manager(sid, "idle")
        if not idle.armed:
            if float(idle.last_t_sec or 0.0) <= 0 and int(idle.ladder_step or 0) == 0:
                idle.reset_decay()
            idle.schedule_next()
        append = self._state_store.poll_frame_manager(sid, "append")
        append.armed = False
        append.next_fire_at = 0.0
        state = self._state_store.session(sid)
        initialized = bool(state.director_cache.get("proactive_loop_initialized"))
        from .responders.request_driven.directors.rhythm_schedule import (
            seed_ladder_executable_units,
        )

        before = sum(
            1
            for e in state.character_rhythm_schedule.executable_units
            if e.status == "pending"
        )
        if not initialized:
            state.character_rhythm_schedule = seed_ladder_executable_units(
                state.character_rhythm_schedule,
                plot_arc=state.plot_arc,
            )
            state.director_cache["proactive_loop_initialized"] = True
        state.director_cache["character_rhythm_schedule"] = (
            state.character_rhythm_schedule.snapshot()
        )
        after = sum(
            1
            for e in state.character_rhythm_schedule.executable_units
            if e.status == "pending"
        )
        logger.info(
            "[Speak] proactive loop bootstrapped session_id=%s pending_opens=%s→%s next_t=%.2fs",
            sid,
            before,
            after,
            float(idle.last_t_sec or 0.0),
        )

    def is_live_warm(self, session_id: str) -> bool:
        """生命线是否已有短期态（切页重连时勿重复 arm 问候）。

        Speak 独立：若已超时静默 / 需再初始化，视为冷接入。
        """
        from .responders.request_driven.orchestrator.state.core.speak_dormant import (
            needs_narrative_reinit,
        )

        sid = session_id.strip()
        if not sid:
            return False
        state = self._state_store.session(sid)
        if needs_narrative_reinit(state) or bool(state.speak_dormant):
            return False
        if state.presence_card.ready:
            return True
        if state.silence_log.ready:
            return True
        if int(state.agent_speak_count or 0) > 0:
            return True
        if float(state.last_user_speak_at or 0.0) > 0:
            return True
        if float(state.last_agent_speak_at or 0.0) > 0:
            return True
        return False

    def enter_page_context(
        self,
        session_id: str,
        *,
        page_key: str,
        messages: list[dict[str, Any]] | None = None,
        lines: list[str] | None = None,
    ) -> dict[str, Any]:
        """进入历史页：把该页对话标记为临时记忆，注入 buffer（最多两代）。

        编剧/导演经 compose materials 调度；不重置 silence/presence 等内在短期态。
        """
        sid = session_id.strip()
        if not sid:
            return {"ok": False, "reason": "missing_session_id"}
        text_lines = list(lines or [])
        if not text_lines and messages:
            text_lines = self._messages_to_page_lines(messages)
        before_ids = {u.unit_id for u in self._page_temp.all_units(sid)}
        gen = self._page_temp.enter_page(sid, page_key=page_key, lines=text_lines)
        after_units = self._page_temp.all_units(sid)
        after_ids = {u.unit_id for u in after_units}
        self._ensure_compose_manager_session(sid, text_lines[0] if text_lines else "")
        for uid in before_ids - after_ids:
            self._compose_gateway.manager.remove_unit(sid, uid)
        if gen.units:
            self._compose_gateway.manager.ingest_units(sid, list(gen.units), kind="page_temp")
        from .responders.request_driven.orchestrator.queue.memory import MemoryBufferItem

        self._orchestrator.compose_queue_hub.set_warm_spread(
            sid,
            MemoryBufferItem(
                turn_index=0,
                lines=tuple(u.text for u in after_units),
                unit_ids=tuple(u.unit_id for u in after_units),
                source="warm_spread",
            ),
        )
        self._refresh_compose_manager_director_meta(
            sid,
            text_lines[0] if text_lines else "page_enter",
        )
        meta = self._compose_manager_meta.get(sid) or {}
        meta["page_temp"] = self._page_temp.snapshot(sid)
        meta["page_temp_active"] = {
            "generation": gen.generation,
            "page_key": gen.page_key,
            "unit_count": len(gen.units),
        }
        self._compose_manager_meta[sid] = meta
        return {
            "ok": True,
            "session_id": sid,
            "generation": gen.generation,
            "page_key": gen.page_key,
            "unit_count": len(gen.units),
            "ring": self._page_temp.snapshot(sid),
        }

    def _messages_to_page_lines(self, messages: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for raw in messages[-40:]:
            if not isinstance(raw, dict):
                continue
            role = str(raw.get("role") or "").strip().lower()
            content = str(raw.get("content") or "").strip()
            if not content:
                continue
            if role in ("user", "human"):
                lines.append(f"用户：{content[:400]}")
            elif role in ("assistant", "agent"):
                lines.append(f"角色：{content[:400]}")
            else:
                lines.append(content[:400])
        return lines

    def cancel_enter_greeting(self, session_id: str) -> None:
        self._session_manager.social.enter_greeting.cancel_session(session_id.strip())

    def seed_warm_spread(self, session_id: str, *, lines: list[str], unit_ids: list[str]) -> None:
        if not unit_ids:
            return
        from .responders.request_driven.orchestrator.queue.memory import MemoryBufferItem

        self._orchestrator.compose_queue_hub.set_warm_spread(
            session_id,
            MemoryBufferItem(
                turn_index=0,
                lines=tuple(lines),
                unit_ids=tuple(unit_ids),
                source="warm_spread",
            ),
        )

    def _has_live_stream_session(self, session_id: str) -> bool:
        port = self._outbound_stream.port
        if port is None:
            return False
        has_connection = getattr(port, "has_connection", None)
        if has_connection is None:
            return True
        return bool(has_connection(session_id))

    @property
    def llm_engine(self) -> SpeakLLMEngine:
        return self._llm

    @property
    def orchestrator(self) -> SpeakOrchestrator:
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
        self._delivery_worker.start()
        if self._orchestrator_thread is not None:
            self._orchestrator_thread.start()
        self._session_manager.social.enter_greeting.start_worker()

    def stop(self) -> None:
        self._session_manager.queues.cancel_all_timers()
        self._session_manager.social.proactive_window.clear_all()
        # 清理可能由旧进程/测试留下的 timer；生产不启动 silence worker。
        self._session_manager.social.silence.stop_worker()
        self._session_manager.social.enter_greeting.stop_worker()
        if self._orchestrator_thread is not None:
            self._orchestrator_thread.stop()
        self._delivery_worker.stop()
        self._queue_decision_runner.stop()
        self._compose_runner.stop()
        from infra.threading import get_thread_registry

        get_thread_registry().stop_owner("speak", timeout=5.0)

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
        self._orchestrator.clear_guidance_control_arc(session_id.strip())

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
        from .responders.request_driven.orchestrator.io.inbound.guidance import GuidancePlanRequest

        sid = session_id.strip()
        resolved_turn = (
            turn_index
            if turn_index is not None
            else self.session_registry.current_turn_index(sid)
        )
        count = share_queue_count
        if count is None:
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
        self._orchestrator.clear_session_compose_state(session_id)
        if self._context is not None:
            self._context.reset_session(session_id)
        self._orchestrator.clear_persona_compose(session_id)
        self._orchestrator.clear_guidance_control_arc(session_id)
        self._rhythm_store.clear_session(session_id)
        sid = session_id.strip()
        self._compose_gateway.manager.reset_session(sid)
        self._compose_manager_sessions.discard(sid)
        self._compose_manager_meta.pop(sid, None)
        self._compose_manager_materials.pop(sid, None)
        self._page_temp.clear(sid)
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
        sid = request.session_id.strip()
        current = self.session_registry.current_turn_index(sid)
        # 新会话 current=0，真正第一轮是 1；预热 0 号位会让进场问候拿到无 frame 的 plan。
        turn_index = current if current > 0 else 1
        generation = self.session_registry.get(sid).generation
        self._compose_runner.schedule_plan_warm(
            self._orchestrator,
            sid,
            target_turn_index=turn_index,
            mode=request.mode,
            reply_style=self._reply_style,
            generation=generation,
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

    def attach_notify_port(self, port) -> None:
        """挂接 notify 适配器（SSE/Bark 等）；可随时连接并冲刷积压。"""
        self._io.outbound.attach_notify_port(port)

    def detach_notify_port(self, port) -> None:
        self._io.outbound.detach_notify_port(port)

    def publish_notify(self, item: dict) -> None:
        """Speak 向外抛通知；无适配器时入内部缓冲。"""
        self._io.outbound.publish_notify(item)

    def enqueue_agent_outbound(self, payload: dict) -> dict:
        """主动会话出站：经 OutboundMessageManager → bus（推出成功即消费）。"""
        result = self._outbound_manager.accept_pending_payload(payload)
        return result.bus or {
            "ok": result.ok,
            "status": result.status,
            "delivered": result.status == "delivered",
        }

    def bind_outbound_snapshot_sink(self, sink) -> None:
        self._io.outbound.bind_snapshot_sink(sink)

    def resolve_outbound_create_ui(
        self,
        delivery_id: str,
        *,
        accepted: bool,
        channel_id: str = "",
        session_id: str = "",
    ) -> dict:
        return self._io.outbound.resolve_create_ui(
            delivery_id,
            accepted=accepted,
            channel_id=channel_id,
            session_id=session_id,
        )

    def acknowledge_outbound_proactive(
        self,
        delivery_id: str,
        *,
        session_id: str = "",
        channel_id: str = "",
    ) -> bool:
        return self._io.outbound.acknowledge_proactive(
            delivery_id,
            session_id=session_id,
            channel_id=channel_id,
        )

    def outbound_snapshot(self) -> dict:
        return self._io.outbound.bus.snapshot()

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
        if self._state_store is not None:
            out["scheduling_state"] = self._state_store.snapshot(sid)
        if self._snapshot_builder is not None:
            snapshot = self._snapshot_builder.build(sid)
            out["session_snapshot"] = snapshot.snapshot()
            out["print"] = print_session_snapshot(snapshot, state_store=self._state_store)
        out["typing"] = self._session_manager.queues._runtime(sid).snapshot_typing()
        out["brew_queue"] = self._session_manager.queues.brew_queue_snapshot(sid)
        if self._orchestrator_thread is not None:
            out["orchestrator_thread"] = self._orchestrator_thread.status()
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
        _ = flush_if_idle
        return {
            "ok": queued,
            "reason": reason,
            "flushed": [],
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
        # 只入酝酿队列，供后续真实回合消费；禁止武装 poll / 直接 flush 占位话题
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
        resolved_turn = turn_index
        if resolved_turn is None and self._turn_coordinator is not None:
            kicked = self._turn_coordinator.state(session_id).turn_index
            if kicked > 0:
                resolved_turn = kicked
        if resolved_turn is None:
            current = self.session_registry.current_turn_index(session_id)
            resolved_turn = current if current > 0 else 1
        director_plan = None
        ledger = None
        if self._turn_coordinator is not None:
            ledger = self._turn_coordinator.inject_ledgers.ledger(
                session_id,
                resolved_turn,
            )
            director_plan = self._turn_coordinator.plan_for_turn(
                session_id,
                resolved_turn,
            )
        if director_plan is None:
            director_plan = self._orchestrator.compose_director.load_plan(
                session_id,
                resolved_turn,
            )
        if director_plan is not None and ledger is not None:
            self._orchestrator.compose_director.apply_memory_kick(
                director_plan,
                self._memory_compose,
                user_text=user_text,
                ledger=ledger,
                mode=mode,
            )
        pulled, portrait_pulled = self._memory_compose.pull_compose_context(
            session_id,
            user_text=user_text,
            turn_index=resolved_turn,
            ledger=ledger,
        )
        get_prompt_trace().emit_event(
            session_id,
            label="compose_memory_context",
            turn_index=resolved_turn,
            payload={
                "user_text": user_text,
                "ledger": ledger.snapshot() if ledger is not None else None,
                "similar_sources": list(pulled.sources),
                "similar_inject_lines": list(pulled.inject.lines),
                "similar_spill_lines": list(pulled.spilled.lines),
                "portrait": {
                    "interactor_id": portrait_pulled.interactor_id,
                    "turn_index": portrait_pulled.turn_index,
                    "portrait_text": portrait_pulled.portrait_text,
                },
            },
        )
        if director_plan is None or director_plan.prepared_frame is None:
            record = self.session_registry.get(session_id)
            # inbound 用户热路径：禁止同步 bootstrap/ensure（会打 plan_control_arc）
            # 拿不到导演新结果就用缓存层先组 bundle，完整 refresh 走异步 warm
            if mode == "inbound":
                director_plan = self._orchestrator.compose_director.hot_path_plan(
                    session_id,
                    target_turn_index=resolved_turn,
                    user_text=user_text,
                    generation=record.generation,
                    mode=mode,
                )
                self._orchestrator.compose_director.save_plan(director_plan)
            elif director_plan is None:
                director_plan = self._orchestrator.compose_director.bootstrap_plan(
                    session_id,
                    target_turn_index=resolved_turn,
                    user_text=user_text,
                    generation=record.generation,
                    bundle_meta=self._orchestrator.compose_cache(session_id).meta_snapshot(),
                    mode=mode,
                )
                self._orchestrator.compose_director.save_plan(director_plan)
            else:
                director_plan = self._orchestrator.compose_director.ensure_prepared_frame(
                    director_plan,
                    user_text=user_text,
                    mode=mode,
                )
                self._orchestrator.compose_director.save_plan(director_plan)

        queued = self._orchestrator.compose_queue_hub.pop_frame(session_id, mode=mode)
        if queued is not None:
            bundle = self._orchestrator.finalize(queued.frame, user_text, session_id=session_id)
            bundle.meta["compose_source"] = "session_queue"
            return self._finish_turn_bundle(
                bundle,
                session_id,
                user_text,
                mode=mode,
                turn_index=resolved_turn,
                similar=pulled,
                portrait=portrait_pulled,
                director_plan=director_plan,
            )

        bundle = self._bundle_from_director_plan(
            director_plan,
            session_id,
            user_text,
            mode=mode,
        )
        if bundle is None:
            if mode == "inbound":
                record = self.session_registry.get(session_id)
                director_plan = self._orchestrator.compose_director.hot_path_plan(
                    session_id,
                    target_turn_index=resolved_turn,
                    user_text=user_text,
                    generation=record.generation,
                    mode=mode,
                )
            else:
                director_plan = self._orchestrator.compose_director.ensure_prepared_frame(
                    director_plan,
                    user_text=user_text,
                    mode=mode,
                )
            self._orchestrator.compose_director.save_plan(director_plan)
            bundle = self._bundle_from_director_plan(
                director_plan,
                session_id,
                user_text,
                mode=mode,
            )
        if bundle is None:
            raise RuntimeError("speak compose requires prepared frame")
        return self._finish_turn_bundle(
            bundle,
            session_id,
            user_text,
            mode=mode,
            turn_index=resolved_turn,
            similar=pulled,
            portrait=portrait_pulled,
            director_plan=director_plan,
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
        queued = self._orchestrator.compose_queue_hub.pop_frame(session_id, mode=mode)
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
        if self._presence is None:
            notes.append("share handoff: no presence")
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
        responder: str | None = None,
    ) -> SpeakTurnResult:
        """用户→角色热路径。导演不得阻塞本接口。

        - 原文先 stamp，并撤掉导演主动 handoff。
        - 若仅因出站推送 / 既有用户 turn 而 queued：打断出站后直达角色。
        - 队列竞态抽干时用 stamp 原文兜底，禁止空 answer（旧 user_input_drained 路径已废）。
        - 导演编排只异步旁路；角色开口不依赖导演完成。
        """
        selected_responder = normalize_speak_responder(responder)
        self._drain_async_delivery_queue()
        self._session_manager.open(session_id, trigger="user_message")
        # 用户原文先落地：撤销导演主动 handoff，再决定是立刻角色回还是打断后回
        self.stamp_user_ingress(session_id, user_text)
        submit = self._session_manager.submit_user_input(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            record=record,
            responder=selected_responder,
        )
        if submit.queued:
            # 打断出站后立刻进角色，不等 pushing / 上一拍 delivery 结束
            if self._session_manager.is_pushing(session_id):
                self._session_manager.end_push(session_id)
            if self._session_manager.user_queue.has_pending(session_id):
                self._session_manager.queues.begin_turn_busy(session_id)
                try:
                    result = self._process_user_inputs(session_id)
                    self._drain_async_delivery_queue()
                    result.notes = list(result.notes) + list(submit.notes) + [
                        "user_direct_after_busy"
                    ]
                    result.meta = {
                        **dict(result.meta),
                        "queued": True,
                        "interrupt": submit.interrupt,
                        "responder": selected_responder,
                    }
                    return result
                finally:
                    self._session_manager.queues.end_turn_busy(session_id)
                    self._flush_pending_character_handoff(session_id)
            # 队列被竞态抽干：禁止空回；用 stamp 原文强制角色回
            stamped = str(
                getattr(self._state_store.session(session_id), "last_real_user_text", "")
                or user_text
                or ""
            ).strip()
            if not stamped:
                raise RuntimeError(
                    "speak: user ingress queued but no stamped text for character reply"
                )
            self._session_manager.queues.begin_turn_busy(session_id)
            try:
                initial = UserInputItem(
                    session_id=session_id,
                    user_text=stamped,
                    mode=mode,
                    stream=stream,
                    record=record,
                    responder=selected_responder,
                    interrupted=bool(submit.interrupt),
                )
                result = self._process_user_inputs(session_id, initial=initial)
                self._drain_async_delivery_queue()
                result.notes = list(result.notes) + list(submit.notes) + [
                    "user_direct_after_busy_stamp_fallback",
                    "never_empty_on_director_drain",
                ]
                result.meta = {
                    **dict(result.meta),
                    "queued": True,
                    "interrupt": submit.interrupt,
                    "responder": selected_responder,
                    "stamp_fallback": True,
                }
                return result
            finally:
                self._session_manager.queues.end_turn_busy(session_id)
                self._flush_pending_character_handoff(session_id)

        self._session_manager.queues.begin_turn_busy(session_id)
        try:
            upcoming = self.session_registry.current_turn_index(session_id) + 1
            self._kick_for_upcoming_turn(session_id, user_text, upcoming, mode=mode)
            initial = UserInputItem(
                session_id=session_id,
                user_text=user_text.strip(),
                mode=mode,
                stream=stream,
                record=record,
                responder=selected_responder,
            )
            result = self._process_user_inputs(session_id, initial=initial)
            self._drain_async_delivery_queue()
            logger.debug("speak prompt bundle: %s", result.bundle.summary_for_log())
            return result
        finally:
            self._session_manager.queues.end_turn_busy(session_id)
            self._flush_pending_character_handoff(session_id)

    def _flush_pending_character_handoff(self, session_id: str) -> None:
        """用户角色 turn/出站空闲后：若有导演主动 due handoff，再请求角色。

        用户优先：若仍有用户队列/打断，不 flush，避免导演再次挡角色接口。
        """
        sid = session_id.strip()
        if not sid or self._orchestrator_thread is None:
            return
        if self._director_must_yield_to_user(sid):
            return
        if self._session_manager.is_pushing(sid) or self._session_manager.is_turn_busy(sid):
            return
        self._orchestrator_thread._maybe_notify_character_handoff(sid)

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
        return self._responder_router.run(item)

    def _clear_async_delivery_ready(self, session_id: str) -> None:
        sid = session_id.strip()
        if not sid:
            return
        with self._async_ready_guard:
            if not self._async_ready_sessions:
                return
            self._async_ready_sessions = deque(
                item for item in self._async_ready_sessions if item != sid
            )

    def _character_decision_llm(self):
        """角色开口决策必须用 DirectorLLMCaller，不能把 SpeakDirectorLLMEngine 再包一层。"""
        caller = getattr(self, "_director_llm_caller", None)
        if caller is not None and getattr(caller, "available", False):
            return caller
        coord = getattr(self, "_director_coordinator", None)
        if coord is not None:
            nested = getattr(coord, "_llm", None)
            if nested is not None and getattr(nested, "available", False):
                return nested
        return None

    def _character_silence_result(
        self,
        *,
        request,
        notes: list[str],
        flush_body: str,
        reason: str,
        note_label: str,
    ):
        from agent.soul.speak.io.outbound.stream.parse.model import SpeakAgentOutput

        from .responders.request_driven.character.interaction import (
            note_character_think_silence,
        )
        from .responders.request_driven.orchestrator.state.core.delivery import (
            build_delivery_plan,
        )
        from .responders.request_driven.timeline import RoleTimeline, TimelineOp

        sid = request.session_id.strip()
        state = self._state_store.session(sid)
        note_character_think_silence(state, reason=reason)
        agenda = getattr(state, "speak_agenda", None)
        if agenda is not None:
            agenda.note_event()
            state.director_cache["speak_agenda"] = agenda.snapshot()
        notes.append(note_label)
        timeline = RoleTimeline(
            ops=(
                TimelineOp(kind="body", body=flush_body or reason),
                TimelineOp(kind="silence", seconds=0.0),
            )
        )
        self._commit_delivery_step(
            session_id=sid,
            request=request,
            answer_text="",
            chose_silence=True,
        )
        empty_plan = build_delivery_plan(
            segments=[],
            continuity="finish",
            plan_id=f"decision-{request.trigger_id}",
            turn_index=int(request.turn_index or 0),
        )
        return (
            "",
            SpeakAgentOutput(session_state="finish"),
            empty_plan,
            True,
            timeline,
        )

    def _character_generate_via_runtime(
        self,
        *,
        request,
        bundle: SpeakPromptBundle,
        notes: list[str],
        director_plan,
        user_text: str,
        record_user_text: str = "",
    ):
        from .responders.request_driven.character.interaction import (
            note_character_exchange,
        )
        from .responders.request_driven.composer.projectors.dynamic_layer import (
            DynamicLayerMaterials,
        )

        sid = request.session_id.strip()
        state = self._state_store.session(sid)
        view = self._compose_gateway.manager.context_for_role(
            sid,
            user_text=user_text,
        )
        materials = self._compose_manager_materials.get(sid)
        if materials is None:
            materials = self._compose_gateway.manager.export_dynamic_materials(
                sid,
                user_text=user_text,
                share_texts=self._collect_share_texts_for_dynamic(sid),
            )
        if not isinstance(materials, DynamicLayerMaterials):
            materials = DynamicLayerMaterials(session_id=sid)
        schedule = self._director_dynamic_schedule(sid)
        result = self._character_runtime.run(
            request,
            bundle=bundle,
            view=view,
            materials=materials,
            schedule=schedule,
            director_plan=director_plan,
            notes=notes,
        )
        answer = str(result.answer_text or "").strip()
        if answer:
            note_character_exchange(
                state,
                user_text=record_user_text,
                agent_text=answer,
            )
        consume_notes = self._finalize_character_reply(result)
        notes[:] = list(result.notes) + list(consume_notes)
        return (
            answer,
            result.parsed,
            result.delivery_plan,
            True,
            result.timeline,
        )

    def _run_user_hot_character_reply(
        self,
        *,
        request,
        bundle: SpeakPromptBundle,
        notes: list[str],
        director_plan,
    ):
        """用户热路径：三选（沉默 / 延迟预约 / 立刻回复）。不与 booked 共用决策。"""
        from .responders.request_driven.character.decision import (
            decide_hot_turn,
            write_hot_delay_booking,
        )
        from .responders.request_driven.character.interaction import (
            export_interaction_record,
            note_character_heard_user,
        )

        sid = request.session_id.strip()
        user_text = request.effective_user_text
        state = self._state_store.session(sid)
        if str(user_text or "").strip():
            note_character_heard_user(
                state,
                user_text=user_text,
                turn_index=int(request.turn_index or 0),
            )

        narrative = getattr(request, "narrative", None)
        plot_intent = str(getattr(narrative, "active_unit_intent", "") or "").strip()
        enrichment = ""
        if narrative is not None and hasattr(narrative, "render_director_instruction"):
            enrichment = narrative.render_director_instruction()
        interaction = export_interaction_record(state).render_for_character()
        decision = decide_hot_turn(
            self._character_decision_llm(),
            session_id=sid,
            turn_index=int(request.turn_index or 0),
            user_text=user_text,
            plot_intent=plot_intent,
            rhythm_enrichment=enrichment,
            interaction_record=interaction,
        )
        notes.append(
            f"hot_decision: action={decision.action} reason={decision.reason[:60]}"
        )
        if decision.action == "silence":
            return self._character_silence_result(
                request=request,
                notes=notes,
                flush_body=decision.flush_body,
                reason=decision.reason,
                note_label="character_chose_silence_after_hot_decision",
            )
        if decision.action == "delay":
            note = write_hot_delay_booking(
                state,
                decision,
                plot_unit_id=str(getattr(narrative, "active_unit_id", "") or "").strip(),
            )
            if note:
                notes.append(note)
            return self._character_silence_result(
                request=request,
                notes=notes,
                flush_body=decision.flush_body,
                reason=decision.reason,
                note_label="character_chose_delay_after_hot_decision",
            )
        return self._character_generate_via_runtime(
            request=request,
            bundle=bundle,
            notes=notes,
            director_plan=director_plan,
            user_text=user_text,
            record_user_text=user_text,
        )

    def _run_booked_character_reply(
        self,
        *,
        request,
        bundle: SpeakPromptBundle,
        notes: list[str],
        director_plan,
    ):
        """预约到点：重建叙事快照后二选（沉默 / 回复）。禁止再预约。"""
        from .responders.request_driven.character.booked_path import decide_booked_turn
        from .responders.request_driven.character.context import build_narrative_snapshot
        from .responders.request_driven.character.interaction import (
            export_interaction_record,
            note_user_silence_on_wake,
        )

        sid = request.session_id.strip()
        state = self._state_store.session(sid)
        origin = str(getattr(request, "origin", "") or "").strip().lower()
        if note_user_silence_on_wake(state):
            notes.append("wake: user_silence_noted")

        # 到点当场重建，不用下预约时的旧材料
        narrative = build_narrative_snapshot(
            state,
            origin=origin or "booked",
            user_text="",
            executable_unit_id=str(getattr(request, "executable_unit_id", "") or ""),
        )
        request.narrative = narrative
        plot_intent = str(getattr(narrative, "active_unit_intent", "") or "").strip()
        enrichment = ""
        if hasattr(narrative, "render_director_instruction"):
            enrichment = narrative.render_director_instruction()
        interaction = export_interaction_record(state).render_for_character()
        decision = decide_booked_turn(
            self._character_decision_llm(),
            session_id=sid,
            turn_index=int(request.turn_index or 0),
            origin=origin or "booked",
            plot_intent=plot_intent,
            rhythm_enrichment=enrichment,
            interaction_record=interaction,
            director_cue=str(getattr(request, "director_cue", "") or ""),
        )
        notes.append(
            f"booked_decision: action={decision.action} reason={decision.reason[:60]}"
        )
        if decision.action == "silence":
            return self._character_silence_result(
                request=request,
                notes=notes,
                flush_body=decision.flush_body,
                reason=decision.reason,
                note_label="character_chose_silence_after_booked_decision",
            )
        return self._character_generate_via_runtime(
            request=request,
            bundle=bundle,
            notes=notes,
            director_plan=director_plan,
            user_text="",
            record_user_text="",
        )

    def _run_character_reply(
        self,
        *,
        request,
        bundle: SpeakPromptBundle,
        notes: list[str],
        director_plan,
    ):
        """按 origin 分发到热路径或预约路径；两条决策互不调用。"""
        origin = str(getattr(request, "origin", "") or "").strip().lower()
        if origin in ("director", "booked"):
            return self._run_booked_character_reply(
                request=request,
                bundle=bundle,
                notes=notes,
                director_plan=director_plan,
            )
        return self._run_user_hot_character_reply(
            request=request,
            bundle=bundle,
            notes=notes,
            director_plan=director_plan,
        )

    def _finalize_character_reply(self, result) -> list[str]:
        """角色回合收尾：消费已压入的记忆/分享；路由角色对导演/编剧的反馈。"""
        from .responders.request_driven.character.consume import consume_injected_materials

        sid = str(result.session_id or "").strip()
        notes: list[str] = []
        if not sid:
            return notes

        def _clear_inject_flags(session_id: str) -> None:
            state = self._state_store.session(session_id)
            flow = getattr(state, "plot_flow", None)
            if flow is not None and hasattr(flow, "clear_material_schedule"):
                flow.clear_material_schedule()
                state.director_cache["plot_flow"] = flow.snapshot()
            # 旧导演 dynamic_layer 缓存不再驱动注入；顺手清掉避免误读
            state.director_cache.pop("dynamic_layer", None)

        presence = self._presence

        def _pop_session_share(session_id: str, index: int):
            return self._session_manager.queues.share_queue.consume_at(
                session_id,
                index,
                turn_index=int(result.turn_index or 0),
                trigger_id=str(result.trigger_id or ""),
            )

        def _peek_session_share(session_id: str):
            return self._session_manager.queues.share_queue.peek_session(session_id)

        def _pop_deferred_matching(session_id: str, topic: str) -> bool:
            # deferred 已并入 session share_queue；再用 topic 精确弹出
            return (
                self._session_manager.queues.share_queue.consume_by_topic(
                    session_id,
                    topic,
                    turn_index=int(result.turn_index or 0),
                    trigger_id=str(result.trigger_id or ""),
                )
                is not None
            )

        notes.extend(
            consume_injected_materials(
                sid,
                memory_unit_ids=tuple(result.consumed_memory_unit_ids or ()),
                share_texts=tuple(result.consumed_share_texts or ()),
                share_indices=tuple(result.consumed_share_indices or ()),
                mark_recall_unit_consumed=self._mark_recall_unit_consumed,
                pop_session_share_at=_pop_session_share,
                pop_presence_share_at=(
                    presence.consume_share_at if presence is not None else None
                ),
                peek_session_share=_peek_session_share,
                pop_deferred_share_matching=_pop_deferred_matching,
                clear_director_inject_flags=_clear_inject_flags,
            )
        )
        share_history = self._session_manager.queues.share_queue.consumption_history(sid)
        if share_history:
            state = self._state_store.session(sid)
            state.director_cache["share_consumption_history"] = share_history
            state.notes.append(
                "dynamic_share: consumed "
                f"count={len(result.consumed_share_texts or ())} "
                f"trigger={result.trigger_id}"
            )
        notes.extend(self._route_character_feedback(sid, result))
        return notes

    def _route_character_feedback(self, session_id: str, result) -> list[str]:
        """角色 note → 导演缓存 / 编剧笔记（不对用户展示）。"""
        sid = session_id.strip()
        notes: list[str] = []
        state = self._state_store.session(sid)
        director_notes = tuple(result.notes_to_director or ())
        writer_notes = tuple(result.notes_to_screenwriter or ())
        if director_notes:
            bucket = list(state.director_cache.get("character_feedback_to_director") or [])
            for item in director_notes:
                text = str(item or "").strip()
                if not text:
                    continue
                bucket.append(
                    {
                        "turn_index": int(result.turn_index or 0),
                        "trigger_id": str(result.trigger_id or ""),
                        "text": text,
                    }
                )
                state.notes.append(f"character→director:{text[:80]}")
            state.director_cache["character_feedback_to_director"] = bucket[-12:]
            notes.append(f"character_feedback_director:{len(director_notes)}")
            # 异步唤醒导演修订时间轴/节奏卡
            coord = getattr(self, "_director_coordinator", None)
            if coord is not None and hasattr(coord, "on_character_feedback"):
                import threading

                threading.Thread(
                    target=coord.on_character_feedback,
                    args=(sid,),
                    name=f"director-feedback-{sid[:12]}",
                    daemon=True,
                ).start()
                notes.append("character_feedback_director_wake_async")
        if writer_notes:
            bucket = list(state.director_cache.get("character_feedback_to_screenwriter") or [])
            for item in writer_notes:
                text = str(item or "").strip()
                if not text:
                    continue
                bucket.append(
                    {
                        "turn_index": int(result.turn_index or 0),
                        "trigger_id": str(result.trigger_id or ""),
                        "text": text,
                    }
                )
                state.notes.append(f"character→screenwriter:{text[:80]}")
            state.director_cache["character_feedback_to_screenwriter"] = bucket[-12:]
            notes.append(f"character_feedback_screenwriter:{len(writer_notes)}")
            # 编剧侧可读：挂到 narrative 缓存供下一拍 poll/refresh 看见
            if getattr(self, "_screenwriter", None) is not None:
                state.director_cache["screenwriter_character_notes"] = list(
                    state.director_cache.get("character_feedback_to_screenwriter") or []
                )[-6:]
        return notes

    def _commit_delivery_step(
        self,
        *,
        session_id: str,
        request,
        answer_text: str,
        chose_silence: bool = False,
    ) -> None:
        """角色可见输出成功后，原子消费唯一 delivery step 并记账。"""
        from .responders.request_driven.orchestrator.state.core.character_rhythm_schedule import (
            plot_progress_fingerprint,
        )

        sid = session_id.strip()
        state = self._state_store.session(sid)
        if request.origin == "user":
            card = state.narrative_card
            card.interaction_mode = "user_utterance"
            card.user_activity = "正在与你文字往来"
            state.director_cache["narrative_card_state"] = card.snapshot()
        step_id = str(getattr(request, "executable_unit_id", "") or "").strip()
        if not step_id:
            return
        if chose_silence or not str(answer_text or "").strip():
            if hasattr(state.character_rhythm_schedule, "release_reserved"):
                state.character_rhythm_schedule.release_reserved(step_id)
                state.director_cache["character_rhythm_schedule"] = (
                    state.character_rhythm_schedule.snapshot()
                )
            return
        # 同对可多次开口：开口不翻卡。节奏+剧情消费只走窗口结束 / 预约跳下一对。
        fingerprint = plot_progress_fingerprint(state.plot_arc, state.plot_flow)
        script = ""
        for entry in state.character_rhythm_schedule.executable_units:
            if entry.unit_id == step_id:
                script = str(entry.script_text or "").strip()
                break
        if hasattr(state.character_rhythm_schedule, "release_reserved"):
            state.character_rhythm_schedule.release_reserved(step_id)
        state.director_cache["character_rhythm_schedule"] = (
            state.character_rhythm_schedule.snapshot()
        )
        agenda = getattr(state, "speak_agenda", None)
        if agenda is not None:
            agenda.note_event()
            state.director_cache["speak_agenda"] = agenda.snapshot()
        ledger = list(state.director_cache.get("delivery_step_ledger") or [])
        ledger.append(
            {
                "delivery_step_id": step_id,
                "origin": str(getattr(request, "origin", "") or ""),
                "trigger_id": str(getattr(request, "trigger_id", "") or ""),
                "plot_unit_ids": list(getattr(request, "plot_unit_ids", ()) or ()),
                "script_text": script[:240],
                "answer_fingerprint": str(answer_text or "").strip()[:120],
                "turn_index": int(getattr(request, "turn_index", 0) or 0),
                "plot_fingerprint": fingerprint,
            }
        )
        state.director_cache["delivery_step_ledger"] = ledger[-24:]
        state.notes.append(
            f"delivery_step: noted exec_unit={step_id} "
            f"origin={request.origin} trigger={request.trigger_id}"
        )
        from .responders.request_driven.character.consume import note_plot_bound_delivery

        # 角色只记账；剧情 unit 完成权在时间轴/议程消费路径 → 编剧
        noted = note_plot_bound_delivery(
            state,
            plot_unit_ids=tuple(getattr(request, "plot_unit_ids", ()) or ()),
            reason=f"character_delivery:{request.origin}",
        )
        if noted:
            state.notes.append(
                f"plot_queue: delivery_noted_await_consume intent={noted[:60]}"
            )

    def _generate_request_driven_with_role_sidechain(
        self,
        *,
        session_id: str,
        bundle: SpeakPromptBundle,
        user_text: str,
        notes: list[str],
        director_plan,
        turn_index: int,
    ):
        """用户直入：拿已有剧情卡构造 origin=user，由角色决定是否开口。

        故意跳过编剧同步以保住交互时延；最新用户交互记入角色侧账本，
        编剧/导演在 poll / refill 时向角色 export_interaction_record 拉取。
        """
        from .responders.request_driven.character import build_character_reply_request

        sid = session_id.strip()
        state = self._state_store.session(sid)
        notes.append(
            "character_pre_sync:skipped_hot_path;"
            "interaction_via_character_export"
        )
        request = build_character_reply_request(
            origin="user",
            session_id=sid,
            turn_index=int(turn_index or 0),
            state=state,
            user_text=user_text,
            reason="user_ingress",
            bind_user_step=True,
        )
        if (
            request.trigger_id
            and state.last_character_trigger_id
            and request.trigger_id == state.last_character_trigger_id
        ):
            notes.append(f"character_duplicate_trigger:{request.trigger_id}")
        out = self._run_user_hot_character_reply(
            request=request,
            bundle=bundle,
            notes=notes,
            director_plan=director_plan,
        )
        state.last_character_trigger_id = request.trigger_id
        answer_text = out[0] if isinstance(out, tuple) and out else ""
        self._commit_delivery_step(
            session_id=sid,
            request=request,
            answer_text=str(answer_text or ""),
            chose_silence=not str(answer_text or "").strip(),
        )
        return out

    def _execute_outbound_request(
        self,
        request: OutboundRequest,
        *,
        user_text: str = "",
        background: bool = False,
    ) -> list[SpeakStreamEvent]:
        outgoing = OutboundRequest(
            session_id=request.session_id,
            ops=request.ops,
            user_text=user_text or request.user_text,
            meta=dict(request.meta),
        )
        message = message_from_request(outgoing, mode="live")

        def _runner(req: OutboundRequest):
            return self._outbound_manager.run_execute(
                req,
                emit_fn=self._stream._emit,
                session_service=self._session_manager,
                stream_channel=self._outbound_stream,
                on_done=(
                    (lambda sid: self._orchestrator_thread.notify_delivery_done(sid))
                    if self._orchestrator_thread is not None
                    else None
                ),
            )

        if background:
            self._session_manager.queues.begin_push(outgoing.session_id, outgoing.user_text)

            def _deliver() -> None:
                self._outbound_manager.dispatch_live(message, runner=_runner)

            self._delivery_worker.submit(_deliver)
            return []
        result = self._outbound_manager.dispatch_live(message, runner=_runner)
        return list(result.events)

    def _deliver_role_timeline(
        self,
        session_id: str,
        timeline,
        *,
        user_text: str = "",
        background: bool = False,
    ) -> list[SpeakStreamEvent]:
        request = timeline_to_outbound_request(
            timeline,
            session_id=session_id,
            user_text=user_text,
            finish=True,
        )
        return self._execute_outbound_request(
            request,
            user_text=user_text,
            background=background,
        )

    def _pace_delivery_plan_with_speak(self, director_plan, speak_text: str):
        from .io.outbound.stream import split_sentences
        from .responders.request_driven.orchestrator.state.core.delivery import (
            ReplySegment,
            build_delivery_plan,
        )

        spoken = speak_text.strip()
        texts = [piece.strip() for piece in split_sentences(spoken, min_chars=8) if piece.strip()]
        if not texts and spoken:
            texts = [spoken]
        templates = list(director_plan.segments)
        if not templates:
            templates = [
                ReplySegment(
                    text="",
                    wait_ms=120,
                    wait_reason="responder",
                    continuity="finish",
                ),
            ]
        segments: list[ReplySegment] = []
        last_index = len(texts) - 1
        for index, text in enumerate(texts):
            tmpl = templates[index] if index < len(templates) else templates[-1]
            continuity = director_plan.continuity if index == last_index else "append"
            segments.append(
                ReplySegment(
                    text=text,
                    wait_ms=int(tmpl.wait_ms or 0),
                    wait_reason=str(tmpl.wait_reason or "").strip(),
                    continuity=continuity,
                ),
            )
        return build_delivery_plan(
            segments=segments,
            continuity=director_plan.continuity,
            sample_narration=director_plan.sample_narration,
            plan_id=director_plan.plan_id,
            turn_index=director_plan.turn_index,
        )

    def _run_request_driven_turn(self, item: UserInputItem) -> SpeakTurnResult:
        sid = item.session_id.strip()
        user_text = item.user_text.strip()
        if not user_text:
            raise RuntimeError("speak: empty user input")

        if item.interrupted:
            ctx = self._session_manager.interrupt_context_for(sid, item)
            if ctx is not None:
                self._orchestrator.compose_queue_hub.prepare_interrupt_turn(sid, ctx)

        upcoming = self.session_registry.current_turn_index(sid) + 1
        self._kick_for_upcoming_turn(sid, user_text, upcoming, mode=item.mode)
        # 故意不 wait_before_compose：角色不得等导演 plan_control_arc / bootstrap
        self._refresh_compose_manager_director_meta(sid, user_text)

        # 用户直达角色：不阻塞等导演；异步旁路仅供下一拍排程
        if self._orchestrator_thread is not None:
            threading.Thread(
                target=self.notify_director_user_input,
                args=(sid, user_text),
                kwargs={"turn_index": upcoming},
                name=f"speak-director-bypass-{sid[:12]}",
                daemon=True,
            ).start()

        state = self._state_store.session(sid)
        plan = state.pending_delivery_plan or state.delivery_plan
        # Sync request_driven owns delivery; drop async ready so director text
        # is not pushed ahead of the main-LLM responder.
        self._clear_async_delivery_ready(sid)
        state.pending_delivery_plan = None
        # 用户入站不受 speak_gate 卡住；角色拿已有剧情卡自行决定是否开口
        state.speak_gate = "speak"

        bundle = self._compose_bundle(sid, user_text, mode=item.mode, turn_index=upcoming)
        notes: list[str] = [
            "request_driven_pipeline",
            "user_direct_to_character",
            "character_no_wait_director_compose",
        ]
        meta: dict[str, object] = {
            "session_state": state.speak_gate,
            "speak_gate": state.speak_gate,
            "request_driven": True,
            "responder": "main_llm",
            "director_cache": dict(state.director_cache),
            "director_delivery_plan": plan.snapshot() if plan is not None else None,
            "pending_plan_snapshot": plan.snapshot() if plan is not None else None,
        }

        if plan is None or plan.is_empty:
            from .responders.request_driven.orchestrator.state.core.delivery import (
                ReplySegment,
                build_delivery_plan,
            )

            plan = build_delivery_plan(
                segments=[
                    ReplySegment(
                        text="",
                        wait_ms=0,
                        wait_reason="user_direct",
                        continuity="finish",
                    ),
                ],
                continuity="finish",
                plan_id=f"user-direct-{sid}-{upcoming}",
                turn_index=upcoming,
            )
            notes.append("user_direct_fallback_delivery_plan")

        director_plan = plan
        answer_text, parsed, paced, used_role, role_timeline = (
            self._generate_request_driven_with_role_sidechain(
                session_id=sid,
                bundle=bundle,
                user_text=user_text,
                notes=notes,
                director_plan=director_plan,
                turn_index=upcoming,
            )
        )
        if used_role:
            meta["responder"] = "speak_role"
            meta["role_timeline"] = True
            notes.append("speak_role_timeline")
        if paced.is_empty and not (used_role and role_timeline is not None):
            notes.append("empty_main_llm_speak")
            meta["session_state"] = parsed.session_state
            meta["director_delivery_plan"] = director_plan.snapshot()
            meta["delivery_plan"] = paced.snapshot()
            get_prompt_trace().emit_event(
                sid,
                label="request_turn_empty_responder",
                turn_index=upcoming,
                payload={
                    "user_text": user_text,
                    "speak_gate": state.speak_gate,
                    "parsed": parsed.to_dict(),
                    "director_plan": director_plan.snapshot(),
                    "notes": notes,
                },
            )
            if self._orchestrator_thread is not None:
                self._orchestrator_thread.notify_delivery_done(sid)
            result = SpeakTurnResult(
                session_id=sid,
                answer="",
                bundle=bundle,
                output=parsed,
                recorded=False,
                notes=notes,
                meta=meta,
            )
            get_prompt_trace().emit_turn_finish(
                sid,
                turn_index=upcoming,
                parsed=parsed,
                answer="",
                notes=result.notes,
                cache=self.session_trace_cache(sid, turn_index=upcoming),
            )
            return result

        self._state_store.set_delivery_plan(sid, paced)
        events: list[SpeakStreamEvent] = []
        if item.stream:
            if used_role and role_timeline is not None:
                events = self._deliver_role_timeline(
                    sid,
                    role_timeline,
                    user_text=user_text,
                    background=True,
                )
        if events:
            stamp = str((events[0].meta or {}).get("created_at") or "").strip()
            if stamp:
                meta["created_at"] = stamp
        if not str(meta.get("created_at") or "").strip():
            from datetime import datetime, timezone

            meta["created_at"] = datetime.now(timezone.utc).isoformat()
        spoken = str(answer_text or "").strip()
        if not spoken:
            spoken = "\n".join(
                segment.text for segment in paced.segments if segment.text.strip()
            )
        recorded = False
        if item.record and spoken:
            self._session_manager.begin_turn(sid)
            self.record_dialogue(sid, user_text, spoken)
            self.note_agent_visible_speak(
                sid,
                turn_index=upcoming,
                user_text=user_text,
                agent_text=spoken,
            )
            recorded = True
            self._on_compose_turn_complete(
                sid,
                user_text,
                spoken,
                upcoming,
                parsed.session_state or paced.continuity,
            )
            self._session_manager.on_turn_complete(
                sid,
                mode=item.mode,
                session_state=parsed.session_state or paced.continuity,
                answer=spoken,
            )
        # timeline 已是唯一出站；turn_finish.answer 再带正文会被前端 dump 成第二站
        answer = (
            ""
            if used_role and role_timeline is not None and item.stream
            else spoken
        )

        if self._orchestrator_thread is not None and not (
            used_role and role_timeline is not None and item.stream
        ):
            self._orchestrator_thread.notify_delivery_done(sid)
        meta["director_delivery_plan"] = director_plan.snapshot()
        meta["delivery_plan"] = paced.snapshot()
        meta["session_state"] = parsed.session_state
        meta["stream_event_count"] = len(events)
        meta["delivered_segment_count"] = len(
            [segment for segment in paced.segments if segment.text.strip()],
        )
        notes.append("main_llm_responder")
        get_prompt_trace().emit_event(
            sid,
            label="request_turn_delivery",
            turn_index=upcoming,
            payload={
                "user_text": user_text,
                "answer": answer,
                "recorded": recorded,
                "stream_event_count": len(events),
                "director_delivery_plan": director_plan.snapshot(),
                "delivery_plan": paced.snapshot(),
                "speak_gate": state.speak_gate,
                "session_state": parsed.session_state,
                "notes": notes,
            },
        )
        result = SpeakTurnResult(
            session_id=sid,
            answer=answer,
            bundle=bundle,
            output=parsed,
            stream_events=events,
            recorded=recorded,
            notes=notes,
            meta=meta,
        )
        get_prompt_trace().emit_turn_finish(
            sid,
            turn_index=upcoming,
            parsed=parsed,
            answer=result.answer,
            notes=result.notes,
            cache=self.session_trace_cache(sid, turn_index=upcoming),
        )
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
        open_outbound: bool = True,
    ) -> dict[str, Any]:
        text = message.strip()
        if not text:
            raise ValueError("speak message cannot be empty")
        self._session_manager.open(
            session_id,
            trigger="proactive_outbound",
            proactive_message=text if open_outbound else "",
            proactive_intent_id=proactive_intent_id,
        )
        brew_meta: dict[str, object] = {}
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
            # 不依赖前端在线：brew 入队，出站经 bus 缓冲/扇出
            self.enqueue_proactive_brew(
                session_id,
                result.speak_reason,
                reason="drive_while_pushing"
                if self._session_manager.is_pushing(session_id)
                else "drive_eval",
                flush_if_idle=(
                    False
                    if self._session_manager.is_pushing(session_id)
                    else not self._session_manager.queues.is_typing_without_idle(session_id)
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
