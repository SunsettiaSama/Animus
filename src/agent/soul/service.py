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
from agent.soul.presence import (
    CaptureEvent,
    IncidentIngestResult,
    LifeIncident,
    PresenceContext,
    PresenceEvent,
    PresenceIngestResult,
    PresenceTrigger,
    SpeakRequest,
    PresenceService,
    Expectation,
)
from agent.soul.presence.transition import (
    PresenceWakeEngine,
    RuminationIngestResult,
    RuminationSignal,
    WakeContext,
)
from agent.soul.handlers.api._llm import resolve_module_llm
from agent.soul.workers import SoulWorkers

from .handlers.api.actions import LifeAction, MemoryAction, PersonaAction, SpeakAction
from .handlers.api.life import LifeHandler
from .handlers.api.memory import MemoryHandler
from .handlers.api.persona import PersonaHandler
from .handlers.tao.backend import AgentServiceTaoBackend
from .handlers.tao.handler import BaseTaoHandler
from .handlers.tao.persona import TaoPersonaHandler
from .ports import EmbeddingPort, LLMServicePort
from .request import SoulChannel, SoulDomain, SoulRequest
from .speak.handler import SpeakHandler
from .presence.interface.egress.react import LightweightReactEngine, PresenceReactOutbound
from .presence.interface.egress.react.ports import ListEmbeddingAdapter
from config.soul.presence.interface_config import InterfaceReactConfig

if TYPE_CHECKING:
    from agent.soul.life.narrative_context import StoryWorldContextSupplier
    from agent.soul.ports import ExternalOpportunitySupplier

logger = logging.getLogger(__name__)


class SoulService:
    """Soul 子系统顶层入口：配置集中、api/tao 双路径、start/stop 生命周期。

    对外语义
    --------
    - ``dispatch(SoulRequest)``：统一命令总线（heartbeat / 内部编排 / 可替代 query_*）
    - ``query_*`` / ``search_memory`` / ``record_*``：HTTP/Tao 工具的语义化薄封装，内部走 dispatch

    生命周期
    --------
    - ``stopped``：拒绝一切访问
    - ``idle`` / ``running``：只读 API action（见 ``access.READ_API_ACTIONS``）可 dispatch
    - ``running``：写入、演化、Tao 通道 action 可 dispatch
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
        tao_handler: BaseTaoHandler | None = None,
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

        self._tao_handler = tao_handler or BaseTaoHandler(
            llm_cfg_path=self._cfg.tao_llm_cfg_path,
            soul=self,
        )
        self._persona_handler: PersonaHandler | None = None
        self._persona_tao_handler: TaoPersonaHandler | None = None
        self._memory_handler: MemoryHandler | None = None
        self._life_handler: LifeHandler | None = None
        self._speak_handler: SpeakHandler | None = None
        self._react_engine: LightweightReactEngine | None = None
        self._react_outbound: PresenceReactOutbound | None = None
        self._embedding_port: EmbeddingPort | None = None
        self._interface_react_cfg: InterfaceReactConfig | None = None
        self._heartbeat: Any = None
        self._orchestrator: HeartbeatOrchestrator | None = None
        self._workers = SoulWorkers()
        self._presence_service: PresenceService | None = None
        self._experience_pipeline: Any = None
        self._speak_service: Any = None
        self._presence_outbound_handlers: list[Any] = []
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
    def persona_tao(self) -> TaoPersonaHandler:
        return self._ensure_persona_tao_handler()

    @property
    def memory(self) -> MemoryHandler:
        return self._ensure_memory_handler()

    @property
    def life(self) -> LifeHandler:
        return self._ensure_life_handler()

    @property
    def tao(self) -> BaseTaoHandler:
        return self._tao_handler

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

    def start_dialogue_session(self, session_id: str = "tao") -> dict[str, Any]:
        """打开对话会话（→ dispatch OPEN_SESSION）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.OPEN_SESSION,
            payload={"session_id": session_id},
        ))

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
        """会话闭合：presence 长体验 → ExperienceUnit → memory。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.speak,
            action=SpeakAction.CLOSE_SESSION,
            payload={"session_id": session_id},
        ))

    def set_embedding_port(self, port: EmbeddingPort | None) -> None:
        """注入顶层 embedding 服务（interface react 会话上下文检索）。"""
        self._embedding_port = port
        if self._react_engine is not None:
            self._react_engine.executor.context_retriever.set_embedder(port)

    def resolve_embedding_port(self) -> EmbeddingPort | None:
        if self._embedding_port is not None:
            return self._embedding_port
        if self._state != "running":
            return None
        backend = self.memory.api.drift_embedder()
        if backend is None:
            return None
        return ListEmbeddingAdapter(backend)

    def run_presence_react_step(
        self,
        session_id: str,
        step: dict[str, Any],
    ) -> dict[str, Any]:
        """轻量 ReAct：解析 step 中追加 action 字段并执行。"""
        self._require_running()
        result = self._ensure_react_engine().run_step(session_id, step)
        return result.to_dict()

    def run_presence_react_chain(
        self,
        session_id: str,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """轻量 ReAct 链式执行（受 max_steps 限制）。"""
        self._require_running()
        result = self._ensure_react_engine().run_chain(session_id, steps)
        return result.to_dict()

    @property
    def interface_react(self) -> LightweightReactEngine:
        return self._ensure_react_engine()

    def register_presence_outbound_handler(
        self,
        handler: Any,
    ) -> None:
        """注册顶层回调：冲动突破限值后发起交互请求。"""
        self._presence_outbound_handlers.append(handler)
        self._ensure_presence_service()
        self._presence_service.set_speak_handler(self._emit_presence_speak)

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
        return self.presence.interface.boundary(
            event,
            context=PresenceContext(
                line_open=line_open,
                proactive_intent_id=proactive_intent_id,
            ),
        )

    def ingest_presence_incident(self, incident: LifeIncident) -> IncidentIngestResult:
        """Life 事件 → presence interface trigger + experience 注入 memory。"""
        self._require_running()
        from agent.soul.presence.experience.sources import ExperienceSource

        source = ExperienceSource.narrative.value
        if incident.kind.value == "surprise":
            source = ExperienceSource.surprise.value
        return self.life_experience.ingest_life_incident(
            self.presence,
            incident,
            fallback_narration=incident.hint,
            salience=incident.salience,
            source=source,
        )

    def ingest_presence_rumination(self, rumination: RuminationSignal) -> RuminationIngestResult:
        """记忆反刍 → presence.interface trigger。"""
        self._require_running()
        result = self.presence.interface.trigger(PresenceTrigger.rumination(rumination))
        if result.outcome.rumination is None:
            raise RuntimeError("rumination trigger did not produce RuminationIngestResult")
        return result.outcome.rumination

    def presence_evolution_event(
        self,
        session_id: str,
        *,
        hint: str,
        salience: float = 0.4,
        trigger: str = "",
        share_desire: str | None = None,
        emotion_text: str = "",
        emotion_intensity: float = 0.0,
        emotion_strength: str = "",
    ) -> CaptureEvent:
        """构造演化事件（经 service 统一出口）。"""
        return self.presence.build_story_beat_event(
            session_id,
            hint=hint,
            salience=salience,
            trigger=trigger,
            share_desire=share_desire,
            emotion_text=emotion_text,
            emotion_intensity=emotion_intensity,
            emotion_strength=emotion_strength,
        )

    def capture_presence_evolution(self, event: CaptureEvent) -> PresenceIngestResult:
        """Soul 内部演化捕获（interface.capture → 冲动累积 → gate → 顶层请求）。"""
        self._require_running()
        return self.presence.interface.capture(event)

    def start(self) -> None:
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError("SoulService 已 stop，请新建实例后再 start")

        self._ensure_memory_handler()
        self.memory.api.init_infra()
        self._ensure_life_handler()
        self._ensure_persona_handler()
        self._ensure_persona_tao_handler()
        self._wire_workers()
        self._workers.start_all()

        self.life.api.load_profile()
        if self._heartbeat is not None:
            self._heartbeat.start_evolution_worker()
        self._state = "running"
        logger.info("[SoulService] started — life_dir=%s", self._life_dir)

    def stop(self) -> None:
        if self._state == "idle":
            return
        if self._heartbeat is not None:
            self._heartbeat.stop_evolution_worker()
        self._workers.stop_all()
        self._orchestrator = None
        self._heartbeat = None
        self._state = "stopped"
        logger.info("[SoulService] stopped")

    def bind_heartbeat(self, heartbeat) -> None:
        """HeartbeatModule 接线：Soul 仅持有编排器引用，不重复创建。"""
        self._heartbeat = heartbeat
        self._orchestrator = heartbeat.orchestrator
        self._ensure_presence_service()
        self.presence.set_timezone(heartbeat.config.active_timezone)
        if self._state == "running":
            heartbeat.start_evolution_worker()

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

    def set_tao_handler(self, handler: BaseTaoHandler) -> None:
        self._tao_handler = handler
        if self._persona_tao_handler is not None:
            self._persona_tao_handler.set_tao_handler(handler)

    def wire_agent_service(self, agent_service) -> None:
        """将 Base Tao 后端切换到 AgentService（与调度器共用 Tao 运行时）。"""
        self._tao_handler.set_backend(AgentServiceTaoBackend(agent_service))
        engine = getattr(agent_service, "engine", None)
        if engine is not None:
            self._tao_handler.set_scheduler_engine(engine)
        if self._orchestrator is not None:
            self._orchestrator.set_scheduler_engine(engine)

    def dispatch(self, request: SoulRequest) -> Any:
        if self._state == "stopped":
            raise RuntimeError(f"SoulService 已停止（state={self._state!r}）")
        if request.channel == SoulChannel.tao:
            self._require_running()
            return self.dispatch_tao(request)
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

    def dispatch_tao(self, request: SoulRequest) -> Any:
        self._require_running()
        if request.domain == SoulDomain.persona:
            return self.persona_tao.handle(request.action, request.payload)
        raise ValueError(f"unknown soul tao domain: {request.domain!r}")

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
        snap = PersonaSnapshot(
            emotional_state=presence_snap.state.affect.narrative,
            attention_keywords=list(persona_snap.get("attention_keywords") or [])[:20],
            tick_id=tid,
        )

        result = self._workers.memory.submit(
            lambda: self.memory.api.tick(snap)
        ).result()
        result.tick_id = tid
        if result.signal.tick_id == "":
            result.signal.tick_id = tid

        rumination = RuminationSignal.from_heartbeat_result(result, session_id="tao")
        rumination_applied = False
        if rumination is not None:
            rumination_result = self.ingest_presence_rumination(rumination)
            rumination_applied = rumination_result.applied
        if not rumination_applied:
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

        outbound = self.presence.flush_accumulated(
            session_id=session_id,
            source="external_opportunity_scan",
            wait_reply=True,
            expectation=Expectation.required,
        )
        return {
            "checked": True,
            "opportune": True,
            "triggered": outbound is not None,
            "session_id": session_id,
        }

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
            "narratives": dict(result.narratives),
        }

    def run_presence_sleep(self, session_id: str = "tao") -> dict[str, Any]:
        """休眠：清空当下态并标记 asleep。"""
        self._require_running()
        result = self.presence.sleep(session_id)
        return {
            "ok": True,
            "applied": result.applied,
            "reason": result.reason,
        }

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

    def query_persona(self) -> dict[str, Any]:
        """只读 Persona 快照 + Presence.affect。"""
        snap = self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.GET_SNAPSHOT,
        ))
        self._ensure_presence_service()
        snap["presence"] = self.presence.snapshot("tao").state.to_dict()
        snap["presence_affect"] = snap["presence"]["affect"]
        return snap

    def record_persona_interaction(
        self,
        question: str,
        answer: str,
        *,
        medium_term_context: str = "",
    ) -> dict[str, Any]:
        """兼容接口：轮级 persona 演化已移除，快变状态见 Presence.affect。"""
        _ = (question, answer, medium_term_context)
        return {
            "ok": True,
            "applied": False,
            "reason": "persona turn evolution removed; use Presence.affect",
        }

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

    def _ensure_persona_tao_handler(self) -> TaoPersonaHandler:
        if self._persona_tao_handler is None:
            self._persona_tao_handler = TaoPersonaHandler(
                tao_handler=self._tao_handler,
                persona_api=self._ensure_persona_handler(),
            )
        return self._persona_tao_handler

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
            self._speak_handler = SpeakHandler(self)
        return self._speak_handler

    def _ensure_experience_pipeline(self):
        if self._experience_pipeline is None:
            from agent.soul.presence.experience import PresenceExperiencePipeline

            self._ensure_presence_service()
            self._ensure_life_handler()
            life = self.life.api
            self._experience_pipeline = PresenceExperiencePipeline(
                life_dir=self._life_dir,
                anchor_chronicle=life.anchor.chronicle,
                virtual_chronicle=life.virtual.chronicle,
                collapser=life.narrative,
            )
            life.attach_experience_pipeline(
                self._experience_pipeline.life,
                dialogue=self._experience_pipeline.dialogue,
            )
        return self._experience_pipeline

    def _ensure_speak_service(self):
        if self._speak_service is None:
            from agent.soul.speak import SpeakService

            self._ensure_experience_pipeline()

            def _record_dialogue_turn(**kwargs) -> None:
                self._experience_pipeline.dialogue.record_dialogue_turn(
                    self.presence,
                    session_id=kwargs["session_id"],
                    user_text=kwargs["question"],
                    agent_text=kwargs["answer"],
                    salience=kwargs.get("salience", 0.3),
                    emotion_label=kwargs.get("emotion_label", ""),
                    valence_delta=kwargs.get("valence_delta", 0.0),
                    arousal_delta=kwargs.get("arousal_delta", 0.0),
                    activated_memory_ids=kwargs.get("activated_memory_ids"),
                    proactive_intent_id=kwargs.get("proactive_intent_id", ""),
                )

            self._speak_service = SpeakService(
                presence=self._presence_service,
                record_turn=_record_dialogue_turn,
            )
        return self._speak_service

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
            from agent.soul.presence.transition import (
                DialogueFsmRefresher,
                DialogueSessionTransition,
                IncidentFsmRefresher,
                IncidentTransition,
                PresenceWakeEngine,
                RuminationFsmRefresher,
                RuminationTransition,
            )

            self._presence_service = PresenceService(
                life_dir=self._life_dir,
                on_speak_request=self._emit_presence_speak,
                wake_engine=PresenceWakeEngine(llm),
                dialogue_transition=DialogueSessionTransition(
                    refresher=DialogueFsmRefresher(llm),
                ),
                incident_transition=IncidentTransition(
                    refresher=IncidentFsmRefresher(llm),
                ),
                rumination_transition=RuminationTransition(
                    refresher=RuminationFsmRefresher(llm),
                ),
                timezone=tz,
            )
        return self._presence_service

    def _emit_presence_speak(self, request: SpeakRequest) -> None:
        self._ensure_react_outbound().handle(request)
        for handler in self._presence_outbound_handlers:
            handler(request)

    def _ensure_react_engine(self) -> LightweightReactEngine:
        if self._react_engine is None:
            cfg = self._interface_react_cfg or InterfaceReactConfig.default()
            self._react_engine = LightweightReactEngine(
                self,
                cfg=cfg,
            )
            embedder = self.resolve_embedding_port()
            if embedder is not None:
                self._react_engine.executor.context_retriever.set_embedder(embedder)
        return self._react_engine

    def _ensure_react_outbound(self) -> PresenceReactOutbound:
        if self._react_outbound is None:
            self._react_outbound = PresenceReactOutbound(self)
        return self._react_outbound

    def _presence_dialogue_overlay_supplier(self, session_id: str):
        from agent.soul.life.anchor.internalization.overlay import InteractionExperienceOverlay

        experience = self.presence.finalize_dialogue_experience(session_id)
        if experience is None:
            return None
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
        from agent.soul.narrative_context_bridge import SoulNarrativeContextSupplier

        self._workers.register_life(self.life.api.worker)
        self.memory.set_worker(self._workers.memory)
        self.persona.set_worker(self._workers.persona)
        self.persona.set_memory_port(self.memory.api)
        self.persona.set_embedder(self.memory.api.drift_embedder())
        self.life.api.set_memory_port(self.memory.api)
        self.life.api.set_narrative_context_supplier(
            SoulNarrativeContextSupplier(self)
        )
        self.life.api.set_story_world_context_supplier(
            self._story_world_context_supplier
        )
        self._ensure_experience_pipeline()
        self._experience_pipeline.life.set_memory_port(self.memory.api)
