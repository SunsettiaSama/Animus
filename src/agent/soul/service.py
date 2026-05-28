from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from config.agent.persona_config import PersonaConfig
from config.storage import StorageConfig
from config.soul.memory.service_config import MemoryServiceConfig
from infra.db.mysql import MySQLClient
from infra.llm import BaseLLM
from infra.memory import MemoryInfraService

from config.soul.config import SoulConfig
from agent.soul.access import is_read_api_action
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
from agent.soul.heartbeat.evolution import new_heartbeat_tick_id
from agent.soul.heartbeat.orchestrator import HeartbeatOrchestrator
from agent.soul.life.experience.incident import IncidentIngestResult, LifeIncident
from agent.soul.presence import (
    Expectation,
    ImpulseDischarge,
    PresenceContext,
    PresenceEvent,
    PresenceIngestResult,
    PresenceService,
    PresenceTrigger,
)
from agent.soul.presence.state.dynamic.expectation.scanner import ExpectationScanPayload
from agent.soul.speak.io import SpeakRequest
from agent.soul.presence.transition import WakeContext
from agent.soul.handlers.api._llm import resolve_module_llm
from agent.soul.workers import SoulWorkers

from .handlers.api.actions import LifeAction, MemoryAction, PersonaAction, SpeakAction
from .handlers.api.life import LifeHandler
from .handlers.api.memory import MemoryHandler
from .handlers.api.persona import PersonaHandler
from .ports import EmbeddingPort, ListEmbeddingAdapter, LLMServicePort
from .request import SoulDomain, SoulRequest
from .speak.io import SpeakOutboundRouter
from .speak.io.handler import SpeakHandler

if TYPE_CHECKING:
    from agent.soul.life.narrative_context import StoryWorldContextSupplier
    from agent.soul.ports import ExternalOpportunitySupplier
    from agent.soul.speak.io.outbound.stream import SpeakStreamPort

logger = logging.getLogger(__name__)


class SoulService:
    """Soul 子系统顶层入口：配置集中、API 命令总线、start/stop 生命周期。

    对外语义
    --------
    - ``dispatch(SoulRequest)``：统一命令总线（heartbeat / 内部编排 / 可替代 query_*）
    - ``query_*`` / ``search_memory`` / ``record_*``：HTTP 语义化薄封装，内部走 dispatch

    生命周期
    --------
    - ``stopped``：拒绝一切访问
    - ``idle`` / ``running``：只读 API action（见 ``access.READ_API_ACTIONS``）可 dispatch
    - ``running``：写入与演化 action 可 dispatch
    """

    def __init__(
        self,
        *,
        life_dir: str,
        persona_cfg: PersonaConfig,
        mysql_client: MySQLClient,
        llm_service: LLMServicePort | None = None,
        primary_llm: BaseLLM | None = None,
        cfg: SoulConfig | None = None,
        memory_cfg: MemoryServiceConfig | None = None,
        memory_infra: MemoryInfraService | None = None,
    ) -> None:
        self._cfg = cfg or SoulConfig.load_default()
        self._memory_cfg = memory_cfg or MemoryServiceConfig.load_default()
        self._state = "idle"
        _storage = StorageConfig()
        self._life_dir = _storage.resolve_life_dir(life_dir)
        _persona_dir = _storage.resolve_persona_dir(persona_cfg.persona_dir)
        if _persona_dir != persona_cfg.persona_dir:
            persona_cfg = replace(persona_cfg, persona_dir=_persona_dir)
        self._persona_cfg = persona_cfg
        self._mysql_client = mysql_client
        self._memory_infra = memory_infra
        self._llm_service = llm_service
        self._primary_llm = primary_llm

        self._persona_handler: PersonaHandler | None = None
        self._memory_handler: MemoryHandler | None = None
        self._life_handler: LifeHandler | None = None
        self._speak_handler: SpeakHandler | None = None
        self._speak_outbound_router: SpeakOutboundRouter | None = None
        self._embedding_port: EmbeddingPort | None = None
        self._heartbeat: Any = None
        self._core_heartbeat: Any = None
        self._scheduler_engine: Any = None
        self._heartbeat_llm_cfg_path: str = "config/llm_core/config.yaml"
        self._orchestrator: HeartbeatOrchestrator | None = None
        self._workers = SoulWorkers()
        self._presence_service: PresenceService | None = None
        self._experience_pipeline: Any = None
        self._speak_service: Any = None
        self._story_world_context_supplier: StoryWorldContextSupplier | None = None
        self._external_opportunity_supplier: ExternalOpportunitySupplier | None = None

    @property
    def config(self) -> SoulConfig:
        return self._cfg

    @property
    def memory_config(self) -> MemoryServiceConfig:
        return self._memory_cfg

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == "running"

    @property
    def orchestrator(self) -> HeartbeatOrchestrator | None:
        return self._orchestrator

    @property
    def persona(self) -> PersonaHandler:
        return self._ensure_persona_handler()

    @property
    def memory(self) -> MemoryHandler:
        return self._ensure_memory_handler()

    @property
    def life(self) -> LifeHandler:
        return self._ensure_life_handler()

    @property
    def workers(self) -> SoulWorkers:
        return self._workers

    @property
    def presence(self) -> PresenceService:
        self._ensure_presence_service()
        return self._presence_service

    @property
    def experience(self):
        self._ensure_experience_pipeline()
        return self._experience_pipeline

    @property
    def dialogue_experience(self):
        self._ensure_experience_pipeline()
        return self._experience_pipeline.dialogue

    @property
    def life_experience(self):
        self._ensure_experience_pipeline()
        return self._experience_pipeline.life

    @property
    def speak(self) -> SpeakHandler:
        return self._ensure_speak_handler()

    @property
    def speak_outbound(self) -> SpeakOutboundRouter:
        return self._ensure_speak_outbound_router()

    def bind_speak_stream_port(self, port: SpeakStreamPort | None) -> None:
        """挂载 Speak 流式出站 port。"""
        self.speak_outbound.bind_stream(port)

    def deliver_speak_text(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> dict[str, Any]:
        """Speak 文本出站（→ DELIVER）。"""
        return self.speak_outbound.deliver_text(session_id, text, final=final)

    def start_dialogue_session(
        self,
        session_id: str = "tao",
        *,
        trigger: str = "user_message",
    ) -> dict[str, Any]:
        """打开 dialogue 体验会话（Speak lifecycle 直连，不经 dispatch）。"""
        self._require_running()
        self._ensure_experience_pipeline()
        state = self.experience.dialogue.open_session(session_id)
        return {
            "ok": True,
            "session_id": session_id,
            "trigger": trigger,
            "turn_count": len(state.session.turns),
        }

    def open_proactive_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> dict[str, Any]:
        """标记 proactive outbound，期待用户回复（Speak lifecycle 直连）。"""
        self._require_running()
        self._ensure_experience_pipeline()
        self.experience.dialogue.open_outbound(
            session_id,
            message,
            proactive_intent_id=proactive_intent_id,
        )
        return {
            "ok": True,
            "session_id": session_id,
            "message": message,
            "proactive_intent_id": proactive_intent_id,
        }

    def record_dialogue_turn(
        self,
        question: str,
        answer: str,
        *,
        session_id: str = "tao",
        perception: str = "",
        narration: str = "",
        prior_thought: str = "",
        emotion: str = "",
        salience_note: str = "",
        valence_note: str = "",
        arousal_note: str = "",
        activated_memory_ids: list[str] | None = None,
        proactive_intent_id: str = "",
    ) -> dict[str, Any]:
        """一轮对话：speak 主观字段一次穿透 presence 与 life/memory 入口。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.RECORD_DIALOGUE,
            payload={
                "session_id": session_id,
                "question": question,
                "answer": answer,
                "perception": perception,
                "narration": narration,
                "prior_thought": prior_thought,
                "emotion": emotion,
                "salience_note": salience_note,
                "valence_note": valence_note,
                "arousal_note": arousal_note,
                "activated_memory_ids": activated_memory_ids,
                "proactive_intent_id": proactive_intent_id,
            },
        ))

    def close_dialogue_interaction(self, session_id: str = "tao") -> dict[str, Any]:
        """会话闭合：life ↔ presence 经 experience stack 直连。"""
        self._require_running()
        self._ensure_experience_pipeline()
        unit = self.experience.close_dialogue(session_id)
        if unit is None:
            return {"ok": True, "session_id": session_id, "ingested": False}
        return {
            "ok": True,
            "session_id": session_id,
            "ingested": True,
            "source": unit.source,
            "turn_index": unit.situation.turn_index,
            "experience_id": unit.id,
        }

    def speak_turn(
        self,
        user_text: str,
        *,
        session_id: str = "tao",
        stream: bool = False,
        mode: str = "inbound",
    ) -> dict[str, Any]:
        """Speak 顶层门面：字块组装 → LLM → 流式推送 → 记账。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.RUN_TURN,
            payload={
                "session_id": session_id,
                "text": user_text,
                "stream": stream,
                "mode": mode,
            },
        ))

    def speak_generate(
        self,
        user_text: str,
        *,
        session_id: str = "tao",
        system: str = "",
        context: str = "",
        stream: bool = False,
    ) -> dict[str, Any]:
        """Speak LLM 直调（不经完整 compose 时可传 system/context）。"""
        action = SpeakAction.GENERATE_STREAM if stream else SpeakAction.GENERATE
        return self.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=action,
            payload={
                "session_id": session_id,
                "text": user_text,
                "system": system,
                "context": context,
            },
        ))

    def set_embedding_port(self, port: EmbeddingPort | None) -> None:
        """注入顶层 embedding 服务。"""
        self._embedding_port = port

    def resolve_embedding_port(self) -> EmbeddingPort | None:
        if self._embedding_port is not None:
            return self._embedding_port
        if self._state != "running":
            return None
        backend = self.memory.api.drift_embedder()
        if backend is None:
            return None
        return ListEmbeddingAdapter(backend)

    def register_presence_outbound_handler(
        self,
        handler: Any,
    ) -> None:
        """注册 speak 出站回调（presence 主动 speak 完成后触发）。"""
        self.speak_outbound.register_after_presence(handler)

    def set_story_world_context_supplier(
        self,
        supplier: StoryWorldContextSupplier | None,
    ) -> None:
        """注入顶层世界观引擎接口（供 life 虚拟编撰按需拉取背景）。"""
        self._story_world_context_supplier = supplier
        self._ensure_life_handler()
        self.life.api.set_story_world_context_supplier(supplier)

    def set_external_opportunity_supplier(
        self,
        supplier: ExternalOpportunitySupplier | None,
    ) -> None:
        """注入外界时机探测接口（供 heartbeat 定期扫描）。"""
        self._external_opportunity_supplier = supplier

    def ingest_presence_event(
        self,
        event: PresenceEvent,
        *,
        line_open: bool = False,
        proactive_intent_id: str = "",
    ) -> PresenceIngestResult:
        """边界事件注入（经 presence.interface）。"""
        self._require_running()
        result = self.presence.interface.boundary(
            event,
            context=PresenceContext(
                line_open=line_open,
                proactive_intent_id=proactive_intent_id,
            ),
        )
        if result.impulse_discharge is not None:
            self._emit_presence_speak(
                self._speak_request_from_discharge(
                    result.impulse_discharge,
                    session_id=event.session_id,
                )
            )
        return result

    def run_presence_sync_cycle(
        self,
        session_id: str = "tao",
        *,
        boundary_event: PresenceEvent | None = None,
        line_open: bool = False,
        proactive_intent_id: str = "",
        scan: bool = True,
        speak_if_ready: bool = True,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Presence 域调度（边界/扫描/speak）；life→presence 同步由 LifeExperienceStack 直连。"""
        self._require_running()

        def _cycle() -> dict[str, Any]:
            detail: dict[str, Any] = {
                "ok": True,
                "session_id": session_id,
                "boundary": None,
                "scan": None,
            }
            if boundary_event is not None:
                ing = self.presence.interface.boundary(
                    boundary_event,
                    context=PresenceContext(
                        line_open=line_open,
                        proactive_intent_id=proactive_intent_id,
                    ),
                )
                boundary_detail: dict[str, Any] = {
                    "notes": list(ing.notes),
                    "impulse_discharge": ing.impulse_discharge is not None,
                }
                if ing.impulse_discharge is not None:
                    self._emit_presence_speak(
                        self._speak_request_from_discharge(
                            ing.impulse_discharge,
                            session_id=session_id,
                        )
                    )
                detail["boundary"] = boundary_detail
            if scan:
                detail["scan"] = self._run_expectation_scan_on_presence(
                    session_id, speak_if_ready=speak_if_ready,
                )
            detail["presence_narrative"] = self.presence_self_narrative(session_id)
            return detail

        if wait:
            return self._workers.presence.submit(_cycle).result()
        self._workers.presence.submit(_cycle)
        return {"accepted": True, "session_id": session_id}

    def presence_self_narrative(self, session_id: str = "tao") -> str:
        """当下自我叙述（由 PresenceService 现场折叠）。"""
        self._ensure_presence_service()
        return self.presence.compose_self_narrative(session_id)

    def initiate_presence_conversation(
        self,
        session_id: str = "tao",
        *,
        source: str = "initiate_conversation",
        wait_reply: bool = True,
    ) -> dict[str, Any]:
        """将当下自我叙述 + 分享队列一并交给 speak 发起回话。"""
        self._require_running()

        def _run() -> dict[str, Any]:
            discharge = self.presence.discharge_accumulated(
                session_id=session_id,
                source=source,
                wait_reply=wait_reply,
                expectation=Expectation.required,
                require_saturated=False,
            )
            if discharge is None:
                return {
                    "ok": False,
                    "session_id": session_id,
                    "reason": "nothing to share",
                }
            request = self._speak_request_from_discharge(discharge, session_id=session_id)
            speak_result = self._emit_presence_speak(request)
            return {
                "ok": True,
                "session_id": session_id,
                "speak": speak_result,
                "presence_narrative": request.presence_narrative,
            }

        return self._workers.presence.submit(_run).result()

    def ingest_presence_incident(self, incident: LifeIncident) -> IncidentIngestResult:
        """Life 事件 → experience unit（presence 同步由 stack 直连触发）。"""
        self._require_running()
        self._ensure_experience_pipeline()
        return self.experience.ingest_incident(incident, salience=incident.salience)

    def start(self) -> None:
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError("SoulService 已 stop，请新建实例后再 start")

        self._ensure_memory_handler()
        self.memory.api.init_infra()
        self._ensure_life_handler()
        self._ensure_persona_handler()
        self._wire_workers()
        self._workers.start_all()
        self._ensure_speak_service().start()

        self.life.api.load_profile()
        hb = self._ensure_heartbeat()
        hb.start_evolution_worker()
        self._start_core_heartbeat()
        self._state = "running"
        logger.info("[SoulService] started — life_dir=%s", self._life_dir)

    def stop(self) -> None:
        if self._state == "idle":
            return
        if self._state == "running":
            self._run_shutdown_memory_sleep()
        self._stop_core_heartbeat()
        if self._heartbeat is not None:
            self._heartbeat.stop_evolution_worker()
        if self._speak_service is not None:
            self._speak_service.stop()
        self._workers.stop_all()
        self._orchestrator = None
        self._heartbeat = None
        self._state = "stopped"
        logger.info("[SoulService] stopped")

    def bind_heartbeat(self, heartbeat) -> None:
        """可选：注入外部 HeartbeatModule；默认由 Soul 在 start() 时自建。"""
        self._heartbeat = heartbeat
        self._orchestrator = heartbeat.orchestrator
        heartbeat.set_soul_service(self)
        self._ensure_presence_service()
        self.presence.set_timezone(heartbeat.config.active_timezone)
        if self._scheduler_engine is not None:
            heartbeat.set_scheduler_engine(self._scheduler_engine)
        if self._state == "running":
            heartbeat.start_evolution_worker()
            self._start_core_heartbeat()

    @property
    def heartbeat(self):
        return self._heartbeat

    @property
    def scheduler_engine(self):
        return self._scheduler_engine

    def force_heartbeat_tick(self):
        self._require_running()
        return self._ensure_heartbeat().tick()

    def status(self) -> dict[str, Any]:
        evolution_status: dict[str, Any] = {}
        if self._heartbeat is not None:
            evolution_status = self._heartbeat.evolution_worker.status()
        workers_status = self._workers.status(orchestration=evolution_status)
        return {
            "state": self._state,
            "life_dir": self._life_dir,
            "config": {
                "heartbeat_scan_interval_sec": self._cfg.heartbeat_scan_interval_sec,
                "memory_ruminate_interval_sec": self._cfg.memory_ruminate_interval_sec,
                "wander_interval_sec": self._cfg.wander_interval_sec,
                "persona_drift_day_of_month": self._cfg.persona_drift_day_of_month,
                "persona_drift_at": self._cfg.persona_drift_at,
                "persona_drift_interval_days": self._cfg.persona_drift_interval_days,
            },
            "workers": workers_status,
            "evolution_worker": evolution_status,
        }

    def bind_scheduler_engine(self, engine) -> None:
        """绑定 runtime 调度引擎（仅 checklist 摘要等只读集成，不驱动 Soul 心跳 tick）。"""
        self._scheduler_engine = engine
        if self._heartbeat is not None:
            self._heartbeat.set_scheduler_engine(engine)
        elif self._orchestrator is not None:
            self._orchestrator.set_scheduler_engine(engine)

    def _ensure_heartbeat(self):
        if self._heartbeat is not None:
            return self._heartbeat
        from agent.soul.heartbeat.config import SoulHeartbeatConfig
        from agent.soul.heartbeat.module import HeartbeatModule

        hb_cfg = SoulHeartbeatConfig.from_soul_config(self._cfg)
        module = HeartbeatModule(
            cfg=hb_cfg,
            log_dir=self._life_dir,
            llm_cfg_path=self._heartbeat_llm_cfg_path,
            soul_config=self._cfg,
        )
        module.set_soul_service(self)
        self._heartbeat = module
        self._orchestrator = module.orchestrator
        self._ensure_presence_service()
        self.presence.set_timezone(hb_cfg.active_timezone)
        if self._scheduler_engine is not None:
            module.set_scheduler_engine(self._scheduler_engine)
        return module

    def _start_core_heartbeat(self) -> None:
        if self._core_heartbeat is not None:
            return
        from agent.soul.heartbeat.core_service import HeartbeatCoreService

        self._core_heartbeat = HeartbeatCoreService(
            heartbeat=self._ensure_heartbeat(),
            llm_service=self._llm_service,
            llm_cfg_path=self._heartbeat_llm_cfg_path,
        )
        self._core_heartbeat.start()

    def _stop_core_heartbeat(self) -> None:
        if self._core_heartbeat is None:
            return
        self._core_heartbeat.stop()
        self._core_heartbeat = None

    def dispatch(self, request: SoulRequest) -> Any:
        if self._state == "stopped":
            raise RuntimeError(f"SoulService 已停止（state={self._state!r}）")
        return self.dispatch_api(request)

    def dispatch_api(self, request: SoulRequest) -> Any:
        self._require_api_access(request)
        if request.domain == SoulDomain.persona:
            return self.persona.handle(request.action, request.payload)
        if request.domain == SoulDomain.memory:
            return self.memory.handle(request.action, request.payload)
        if request.domain == SoulDomain.life:
            return self.life.handle(request.action, request.payload)
        if request.domain == SoulDomain.speak:
            return self.speak.handle(request.action, request.payload)
        raise ValueError(f"unknown soul api domain: {request.domain!r}")

    def run_wander(
        self, drift_intensity_floor: float | None = None
    ) -> tuple[MemoryHeartbeatResult, list[dict]]:
        """跨域 wander：memory tick → presence rumination/affect → life。"""
        from agent.soul.heartbeat.bridge import PersonaSnapshot

        self._require_running()
        floor = (
            drift_intensity_floor
            if drift_intensity_floor is not None
            else self._cfg.wander_drift_intensity_floor
        )
        tid = new_heartbeat_tick_id()
        presence_snap = self.presence.snapshot("tao")
        persona_snap = self.persona.service.snapshot()
        from agent.soul.speak.compose.injected.persona import collect_persona_injected

        injected = collect_persona_injected(persona_snap=persona_snap)
        persona_profile = "\n\n".join(
            part for part in (injected.traits, injected.self_concept) if part
        )
        snap = PersonaSnapshot(
            emotional_state=presence_snap.state.affect.narrative,
            attention_keywords=list(persona_snap.get("attention_keywords") or [])[:20],
            persona_profile=persona_profile,
            tick_id=tid,
        )

        result = self._workers.memory.submit(
            lambda: self.memory.api.tick(snap)
        ).result()
        result.tick_id = tid
        if result.signal.tick_id == "":
            result.signal.tick_id = tid

        self.presence.receive_heartbeat_signal(
            result.signal,
            session_id="tao",
            intensity_floor=floor,
        )
        self._record_persona_cluster_signals(result.buffer_candidates)
        story_beats = self._workers.life.submit(
            lambda: self.life.api.apply_wander_experience(result)
        ).result()
        return result, story_beats

    def run_memory_sleep(self, *, dry_run: bool = False) -> dict:
        """记忆睡眠巩固：遗忘扫描、聚类重建、反刍缓冲衰减。"""
        from agent.soul.heartbeat.evolution import new_heartbeat_tick_id

        self._require_running()
        tid = new_heartbeat_tick_id()
        result = self._workers.memory.submit(
            lambda: self.memory.api.run_sleep(tick_id=tid, dry_run=dry_run)
        ).result()
        return result.to_dict()

    def run_trigger_landmarks(self) -> list[dict]:
        self._require_running()
        return self._workers.life.submit(
            lambda: self.life.api.fill_due_landmarks()
        ).result()

    def run_surprise_tick(self, elapsed_sec: float) -> dict:
        self._require_running()
        return self._workers.life.submit(
            lambda: self.life.api.run_surprise_tick(elapsed_sec)
        ).result()

    def run_external_opportunity_scan(self, session_id: str = "tao") -> dict[str, Any]:
        self._require_running()
        supplier = self._external_opportunity_supplier
        if supplier is None:
            return {"checked": False, "reason": "no supplier", "triggered": False}

        snap = self.presence.snapshot(session_id)
        opportune = bool(supplier.is_opportune(
            session_id=session_id,
            impulse_level=snap.impulse_level,
            expectation=snap.expectation.value,
        ))
        if not opportune:
            return {"checked": True, "opportune": False, "triggered": False}

        discharge = self.presence.discharge_accumulated(
            session_id=session_id,
            source="external_opportunity_scan",
            wait_reply=True,
            expectation=Expectation.required,
        )
        triggered = discharge is not None
        if discharge is not None:
            self._emit_presence_speak(
                self._speak_request_from_discharge(discharge, session_id=session_id)
            )
        return {
            "checked": True,
            "opportune": True,
            "triggered": triggered,
            "session_id": session_id,
        }

    def run_expectation_scan(self, session_id: str = "tao") -> dict[str, Any]:
        """期待扫描：presence 更新状态，Soul 层决定是否 speak。"""
        self._require_running()
        return self._workers.presence.submit(
            lambda: self._run_expectation_scan_on_presence(session_id, speak_if_ready=True)
        ).result()

    def _run_expectation_scan_on_presence(
        self,
        session_id: str,
        *,
        speak_if_ready: bool,
    ) -> dict[str, Any]:
        scan = self.presence.scan_expectation(session_id)
        detail: dict[str, Any] = {
            "session_id": scan.session_id,
            "triggered": scan.triggered,
            "mode": scan.mode.value,
            "notes": list(scan.notes),
        }
        if speak_if_ready and scan.triggered and scan.payload is not None:
            request = self._speak_request_from_scan(scan.payload, session_id=session_id)
            self._emit_presence_speak(request)
            detail["speak_source"] = request.source
        return detail

    def run_presence_wake(self, session_id: str = "tao", *, force: bool = False) -> dict[str, Any]:
        """起床：Presence FSM 四维度自叙初始化（演化入口）。"""
        self._require_running()
        ctx = self._build_wake_context()
        result = self.presence.wake_up(session_id, context=ctx, force=force)
        return {
            "ok": True,
            "applied": result.applied,
            "source": result.source,
            "reason": result.reason,
            "narratives": dict(result.narratives or {}),
        }

    def run_presence_sleep(self, session_id: str = "tao") -> dict[str, Any]:
        """休眠：清空当下态并标记 asleep，并触发一次记忆睡眠巩固。"""
        self._require_running()
        result = self.presence.sleep(session_id)
        memory_sleep = self.run_memory_sleep()
        return {
            "ok": True,
            "applied": result.applied,
            "reason": result.reason,
            "memory_sleep": memory_sleep,
        }

    def _run_shutdown_memory_sleep(self) -> None:
        if self.presence.is_awake():
            self.run_presence_sleep()
            return
        self.run_memory_sleep()

    def _build_wake_context(self) -> WakeContext:
        snap = self.query_persona()
        profile = snap.get("profile") or {}
        concept = snap.get("self_concept") or {}
        tz = "Asia/Shanghai"
        if self._heartbeat is not None:
            tz = self._heartbeat.config.active_timezone
        summary_parts: list[str] = []
        background = str(profile.get("background", "")).strip()
        if background:
            summary_parts.append(background)
        traits = profile.get("traits") or profile.get("core_traits") or []
        if traits:
            summary_parts.append("特质：" + "、".join(str(t) for t in traits[:5]))
        style = str(profile.get("style", "")).strip()
        if style:
            summary_parts.append(f"风格：{style}")
        return WakeContext(
            agent_name=str(profile.get("name", "")),
            persona_summary="\n".join(summary_parts),
            self_narrative=str(concept.get("narrative", "")),
            timezone=tz,
        )

    def execute_plan_landmark(self) -> dict[str, Any]:
        """在 life-worker 线程内执行地标规划（compose + add）。"""
        from datetime import datetime, timezone

        from agent.soul.heartbeat.checklist.landmark_schedule import (
            compute_landmark_trigger_at,
            landmark_window_start,
        )

        cfg = self._cfg
        now = datetime.now(timezone.utc)
        since = landmark_window_start(now, window_hours=cfg.landmark_write_window_hours)
        lm = self.life.api
        written = lm.count_landmarks_written_since(since.isoformat())
        if written >= cfg.landmark_write_max_per_window:
            return {
                "planned": False,
                "reason": "window quota",
                "written": written,
                "window_hours": cfg.landmark_write_window_hours,
                "max_per_window": cfg.landmark_write_max_per_window,
            }

        draft = lm.compose_landmark()
        if draft is None:
            return {"planned": False, "reason": "no llm or compose failed"}

        scheduled_at = compute_landmark_trigger_at(
            now,
            gap_rounds=cfg.landmark_write_gap_rounds,
            round_sec=cfg.landmark_trigger_interval_sec,
        )
        planned_event = lm.plan_landmark(
            intention=draft["intention"],
            scheduled_at=scheduled_at.isoformat(),
            context=draft.get("context", ""),
        )
        ok = planned_event is not None
        return {
            "planned": bool(ok),
            "intention": draft["intention"],
            "context": draft.get("context", ""),
            "scheduled_at": scheduled_at.isoformat(),
            "gap_rounds": cfg.landmark_write_gap_rounds,
            "trigger_round_sec": cfg.landmark_trigger_interval_sec,
            "written_in_window": written + (1 if ok else 0),
            "subjective_event": planned_event or {},
        }

    # ── 对外查询接口（HTTP / 外部集成）────────────────────────────────────────

    def query_persona(self, *, session_id: str = "tao") -> dict[str, Any]:
        """只读 Persona 快照 + Presence 在线自我叙述（外部请求可直出）。"""
        snap = self.get_persona_snapshot(session_id=session_id)
        self._ensure_presence_service()
        snap["presence"] = self.presence.snapshot(session_id).state.to_dict()
        snap["presence_affect"] = snap["presence"]["affect"]
        snap["presence_self_narrative"] = self.presence_self_narrative(session_id)
        return snap

    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict[str, Any]:
        """Speak compose 用：仅 persona 稳定层 + self_concept（不含 presence）。"""
        _ = session_id
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.GET_SNAPSHOT,
        ))

    def reload_persona_profile(self) -> dict[str, Any]:
        """热加载 persona_dir 下的 profile / built_profile / self_concept。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.RELOAD_PROFILE,
        ))

    def rebuild_persona_profile(
        self,
        *,
        preserve_self_concept: bool = False,
    ) -> dict[str, Any]:
        """LLM 规范化 raw profile 并写盘；默认同时重置 self_concept。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.REBUILD_PROFILE,
            payload={"preserve_self_concept": preserve_self_concept},
        ))

    def search_memory(self, mode: str = "hybrid", **kwargs: Any) -> dict[str, Any]:
        """记忆检索（→ dispatch SEARCH）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.memory,
            action=MemoryAction.SEARCH,
            payload={"mode": mode, **kwargs},
        ))

    def recall_memory(
        self,
        query: str,
        *,
        top_k: int | None = None,
        emotional_context: str = "",
    ) -> dict[str, Any]:
        """记忆 recall（→ dispatch RECALL）。"""
        payload: dict[str, Any] = {"query": query, "emotional_context": emotional_context}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.dispatch(SoulRequest(
            domain=SoulDomain.memory,
            action=MemoryAction.RECALL,
            payload=payload,
        ))

    def query_life_chronicle(self, *, days: int = 7, tail: int = 50) -> list[dict[str, Any]]:
        """Life 近期 Chronicle 经历（→ dispatch RECENT_CHRONICLE）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.life,
            action=LifeAction.RECENT_CHRONICLE,
            payload={"days": days, "tail": tail},
        ))

    def query_life_hot(self, *, hours: int | None = None) -> list[dict[str, Any]]:
        """Life 当前热存储（→ dispatch HOT_STORAGE）。"""
        payload: dict[str, Any] = {}
        if hours is not None:
            payload["hours"] = hours
        return self.dispatch(SoulRequest(
            domain=SoulDomain.life,
            action=LifeAction.HOT_STORAGE,
            payload=payload,
        ))

    def _require_api_access(self, request: SoulRequest) -> None:
        if self._state == "stopped":
            raise RuntimeError(f"SoulService 已停止（state={self._state!r}）")
        if is_read_api_action(request.domain, request.action):
            return
        self._require_running()

    def _require_running(self) -> None:
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行（state={self._state!r}），请先 start()")

    def _ensure_persona_handler(self) -> PersonaHandler:
        if self._persona_handler is None:
            self._persona_handler = PersonaHandler(
                cfg=self._persona_cfg,
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.persona_llm_aux_name,
                primary_llm=self._primary_llm,
            )
        return self._persona_handler

    def _ensure_memory_handler(self) -> MemoryHandler:
        if self._memory_handler is None:
            self._memory_handler = MemoryHandler(
                mysql_client=self._mysql_client,
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.memory_llm_aux_name,
                primary_llm=self._primary_llm,
                cfg=self._memory_cfg,
                soul_config=self._cfg,
                memory_infra=self._memory_infra,
            )
        return self._memory_handler

    def _ensure_life_handler(self) -> LifeHandler:
        if self._life_handler is None:
            self._ensure_presence_service()
            self._life_handler = LifeHandler(
                life_dir=self._life_dir,
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.life_llm_aux_name,
                primary_llm=self._primary_llm,
            )
            self._life_handler.api.set_story_world_context_supplier(
                self._story_world_context_supplier
            )
        return self._life_handler

    def _ensure_speak_handler(self) -> SpeakHandler:
        if self._speak_handler is None:
            self._speak_handler = SpeakHandler(
                self,
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.speak_llm_aux_name,
                primary_llm=self._primary_llm,
            )
        return self._speak_handler

    def _ensure_experience_pipeline(self):
        if self._experience_pipeline is None:
            from agent.soul.life.experience import LifeExperienceStack

            self._ensure_presence_service()
            self._ensure_life_handler()
            life = self.life.api
            self._experience_pipeline = LifeExperienceStack(
                life_dir=self._life_dir,
                anchor_chronicle=life.anchor.chronicle,
                virtual_chronicle=life.virtual.chronicle,
                collapser=life.narrative,
            )
            life.attach_experience_pipeline(
                self._experience_pipeline.life,
                dialogue=self._experience_pipeline.dialogue,
            )
            self._experience_pipeline.bind_presence(self._presence_service)
        return self._experience_pipeline

    def _ensure_speak_service(self):
        if self._speak_service is None:
            from agent.soul.speak import SpeakService
            from agent.soul.speak.llm.engine import SpeakLLMEngine

            self._ensure_experience_pipeline()

            def _record_dialogue_turn(**kwargs) -> None:
                self._experience_pipeline.record_dialogue_turn(
                    session_id=kwargs["session_id"],
                    user_text=kwargs.get("user_text", kwargs.get("question", "")),
                    agent_text=kwargs.get("agent_text", kwargs.get("answer", "")),
                    salience=kwargs.get("salience", 0.3),
                    emotion_label=kwargs.get("emotion_label", ""),
                    valence_delta=kwargs.get("valence_delta", 0.0),
                    arousal_delta=kwargs.get("arousal_delta", 0.0),
                    activated_memory_ids=kwargs.get("activated_memory_ids"),
                    proactive_intent_id=kwargs.get("proactive_intent_id", ""),
                )

            def _touch_dialogue(session_id: str) -> None:
                state = self._experience_pipeline.dialogue.state(session_id)
                if state is not None:
                    state.touch()

            flush_mode = self._cfg.speak_stream_flush_mode
            if flush_mode not in {"segment", "token_batch"}:
                flush_mode = "segment"

            self._speak_service = SpeakService(
                presence=self._presence_service,
                persona=self,
                record_turn=_record_dialogue_turn,
                llm_engine=SpeakLLMEngine(
                    resolve_module_llm(
                        self._llm_service,
                        self._cfg.speak_llm_aux_name,
                        self._primary_llm,
                    )
                ),
                flush_mode=flush_mode,  # type: ignore[arg-type]
                share_threshold=self._cfg.speak_share_proactive_threshold,
                session_idle_sec=self._cfg.speak_session_idle_sec,
                semantic_distance_threshold=self._cfg.speak_session_semantic_distance_threshold,
                embedder=self.resolve_embedding_port(),
                context_distill_chunk_size=self._cfg.speak_context_distill_chunk_size,
                memory_turn_gap=self._memory_cfg.memory_turn_proximity_max,
                lifecycle=self,
                touch_dialogue=_touch_dialogue,
            )
            from agent.soul.speak.io.inbound.memory import (
                PointQueryRequest,
                RecallRequest,
                RecallResult,
                SimilarMemoryBlock,
                SimilarMemoryPullResult,
            )

            def _recall_for_speak(request: RecallRequest) -> RecallResult:
                payload = self.recall_memory(
                    request.query,
                    top_k=request.top_k,
                )
                return RecallResult(
                    ok=True,
                    query=request.query,
                    text=str(payload.get("text", "")),
                )

            def _point_query_for_speak(request: PointQueryRequest) -> None:
                self.memory.api.request_speak_point_query(
                    session_id=request.session_id,
                    interactor_id=request.interactor_id,
                    turn_index=request.turn_index,
                    user_text=request.user_text,
                    agent_text=request.agent_text,
                )

            def _pull_similar_for_speak(session_id: str, turn_index: int) -> SimilarMemoryPullResult:
                consumed = self._speak_service.session_manager.consume_memory_for_compose(
                    session_id,
                    turn_index,
                )
                return SimilarMemoryPullResult(
                    inject=SimilarMemoryBlock(
                        turn_index=consumed.inject_turn_index or turn_index,
                        lines=list(consumed.inject_lines),
                        unit_ids=list(consumed.inject_unit_ids),
                    ),
                    spilled=SimilarMemoryBlock(
                        turn_index=consumed.spilled_turn_index,
                        lines=list(consumed.spilled_lines),
                        unit_ids=list(consumed.spilled_unit_ids),
                    ),
                )

            def _on_point_emergence_ready(result) -> None:
                self._speak_service.session_manager.enqueue_memory_result(
                    result.session_id,
                    turn_index=result.turn_index,
                    lines=result.merged_lines(),
                    unit_ids=result.merged_unit_ids(),
                    associative_ready=result.associative_ready,
                )

            self._speak_service.attach_memory_recall(_recall_for_speak)
            self._speak_service.attach_memory_point_query(_point_query_for_speak)
            self._speak_service.attach_memory_pull_similar(_pull_similar_for_speak)
            self.memory.api.on_point_emergence_ready(_on_point_emergence_ready)
        return self._speak_service

    def _relay_presence_status_to_speak(self, snap) -> None:
        if self._speak_service is not None:
            self._speak_service.on_presence_status_update(snap)

    def _ensure_presence_service(self) -> PresenceService:
        if self._presence_service is None:
            tz = "Asia/Shanghai"
            if self._heartbeat is not None:
                tz = self._heartbeat.config.active_timezone
            llm = resolve_module_llm(
                self._llm_service,
                self._cfg.presence_llm_aux_name,
                self._primary_llm,
            )
            _ = llm
            self._presence_service = PresenceService(
                life_dir=self._life_dir,
                timezone=tz,
            )
            self._presence_service.register_status_update_listener(
                self._relay_presence_status_to_speak,
            )
        return self._presence_service

    def _speak_request_from_discharge(
        self,
        discharge: ImpulseDischarge,
        *,
        session_id: str | None = None,
    ) -> SpeakRequest:
        sid = session_id or discharge.session_id
        narrative = self.presence_self_narrative(sid)
        reason = discharge.reason
        if narrative and narrative not in reason:
            reason = f"{reason}\n\n【当下】\n{narrative}" if reason else narrative
        return SpeakRequest(
            session_id=sid,
            reason=reason,
            impulse_level=discharge.impulse_level,
            share_desire=discharge.share_desire,
            expectation=discharge.expectation,
            package=discharge.package,
            source=discharge.source,
            wait_reply=discharge.wait_reply,
            presence_narrative=narrative,
        )

    def _speak_request_from_scan(
        self,
        payload: ExpectationScanPayload,
        *,
        session_id: str,
    ) -> SpeakRequest:
        narrative = self.presence_self_narrative(session_id)
        reason = payload.reason
        if narrative and narrative not in reason:
            reason = f"{reason}\n\n【当下】\n{narrative}" if reason else narrative
        return SpeakRequest(
            session_id=session_id,
            reason=reason,
            impulse_level=payload.impulse_level,
            share_desire=payload.share_desire,
            expectation=payload.expectation,
            package=payload.package,
            source=payload.source,
            wait_reply=payload.wait_reply,
            presence_narrative=narrative,
        )

    def _emit_presence_speak(self, request: SpeakRequest) -> dict[str, Any]:
        return self.speak_outbound.emit_presence(request)

    def _ensure_speak_outbound_router(self) -> SpeakOutboundRouter:
        if self._speak_outbound_router is None:
            self._speak_outbound_router = SpeakOutboundRouter(self)
        return self._speak_outbound_router

    def _presence_dialogue_overlay_supplier(self, session_id: str):
        from agent.soul.life.anchor.internalization.overlay import InteractionExperienceOverlay
        from agent.soul.life.experience.dialogue.experience import build_dialogue_experience

        snap = self.presence.snapshot(session_id)
        if snap.state.is_empty():
            return None
        experience = build_dialogue_experience(snap.state)
        return InteractionExperienceOverlay(
            perception=experience.perception,
            narration=experience.narration,
            emotion_label=experience.emotion_label,
        )

    def _record_persona_cluster_signals(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """Memory.persona_clusters 元数据 → PersonaService.record_cluster_signals。"""
        if not candidates:
            return {"ok": True, "applied": 0, "signal_ids": []}
        return self._workers.persona.submit(
            lambda: self.persona.service.record_cluster_signals(candidates)
        ).result()

    def _wire_workers(self) -> None:
        self._workers.register_life(self.life.api.worker)
        self.memory.set_worker(self._workers.memory)
        self.persona.set_worker(self._workers.persona)
        self.persona.set_memory_port(self.memory.api)
        self.persona.set_embedder(self.memory.api.drift_embedder())
        self.life.api.set_memory_port(self.memory.api)
        self.life.api.set_story_world_context_supplier(
            self._story_world_context_supplier
        )
        self._ensure_experience_pipeline()
        self._experience_pipeline.life.set_memory_port(self.memory.api)
