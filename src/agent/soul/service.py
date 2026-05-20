from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from config.agent.persona_config import PersonaConfig
from config.storage import StorageConfig
from config.soul.memory.service_config import MemoryServiceConfig
from infra.db.mysql import MySQLClient
from infra.db.redis import RedisClient
from infra.llm import BaseLLM

from config.soul.config import SoulConfig
from agent.soul.access import is_read_api_action
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
from agent.soul.heartbeat.evolution import new_heartbeat_tick_id
from agent.soul.heartbeat.orchestrator import HeartbeatOrchestrator
from agent.soul.drive import (
    CaptureEvent,
    DriveContext,
    DriveEvent,
    DriveIngestResult,
    DriveOutboundRequest,
    DriveService,
    Expectation,
)
from agent.soul.workers import SoulWorkers

from .handlers.api.actions import LifeAction, MemoryAction, PersonaAction
from .handlers.api.life import LifeHandler
from .handlers.api.memory import MemoryHandler
from .handlers.api.persona import PersonaHandler
from .handlers.tao.backend import AgentServiceTaoBackend
from .handlers.tao.handler import BaseTaoHandler
from .handlers.tao.persona import TaoPersonaHandler
from .ports import LLMServicePort
from .request import SoulChannel, SoulDomain, SoulRequest

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
        redis_client: RedisClient,
        mysql_client: MySQLClient,
        llm_service: LLMServicePort | None = None,
        primary_llm: BaseLLM | None = None,
        cfg: SoulConfig | None = None,
        memory_cfg: MemoryServiceConfig | None = None,
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
        self._redis_client = redis_client
        self._mysql_client = mysql_client
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
        self._heartbeat: Any = None
        self._orchestrator: HeartbeatOrchestrator | None = None
        self._workers = SoulWorkers()
        self._drive_service: DriveService | None = None
        self._drive_outbound_handlers: list[Any] = []
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
    def drive(self) -> DriveService:
        self._ensure_drive_service()
        return self._drive_service

    def register_drive_outbound_handler(
        self,
        handler: Any,
    ) -> None:
        """注册顶层回调：冲动突破限值后发起交互请求。"""
        self._drive_outbound_handlers.append(handler)
        self._ensure_drive_service()
        self._drive_service.set_outbound_handler(self._emit_drive_outbound)

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

    def ingest_drive_event(
        self,
        event: DriveEvent,
        *,
        line_open: bool = False,
        proactive_intent_id: str = "",
    ) -> DriveIngestResult:
        """顶层边界事件注入（capture → transition → gate）。"""
        self._require_running()
        return self.drive.ingest(
            event,
            context=DriveContext(
                line_open=line_open,
                proactive_intent_id=proactive_intent_id,
            ),
        )

    def capture_drive_evolution(self, event: CaptureEvent) -> DriveIngestResult:
        """Soul 内部演化捕获（capture → 冲动累积 → gate → 顶层请求）。"""
        self._require_running()
        return self.drive.capture_evolution(event)

    def start(self) -> None:
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError("SoulService 已 stop，请新建实例后再 start")

        self._ensure_memory_handler()
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
                "persona_reflection_interval_sec": self._cfg.persona_reflection_interval_sec,
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
        raise ValueError(f"unknown soul api domain: {request.domain!r}")

    def dispatch_tao(self, request: SoulRequest) -> Any:
        self._require_running()
        if request.domain == SoulDomain.persona:
            return self.persona_tao.handle(request.action, request.payload)
        raise ValueError(f"unknown soul tao domain: {request.domain!r}")

    def run_wander(
        self, drift_intensity_floor: float | None = None
    ) -> tuple[MemoryHeartbeatResult, list[dict]]:
        """跨域 wander pipeline：persona 读态 → memory tick → persona/life 异步入账。"""
        self._require_running()
        floor = (
            drift_intensity_floor
            if drift_intensity_floor is not None
            else self._cfg.wander_drift_intensity_floor
        )
        tid = new_heartbeat_tick_id()
        snap = self._workers.persona.submit(
            lambda: self.persona.api.read_state()
        ).result()
        snap.tick_id = tid

        result = self._workers.memory.submit(
            lambda: self.memory.api.tick(snap)
        ).result()
        result.tick_id = tid
        if result.signal.tick_id == "":
            result.signal.tick_id = tid

        self._workers.persona.enqueue(
            lambda: self.persona.api.apply_wander_result(result, floor)
        )
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

        snap = self.drive.snapshot(session_id)
        opportune = bool(supplier.is_opportune(
            session_id=session_id,
            impulse_level=snap.impulse_level,
            expectation=snap.expectation.value,
        ))
        if not opportune:
            return {"checked": True, "opportune": False, "triggered": False}

        outbound = self.drive.flush_accumulated(
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
        """只读 Persona 快照（→ dispatch GET_SNAPSHOT）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.GET_SNAPSHOT,
        ))

    def record_persona_interaction(
        self,
        question: str,
        answer: str,
        *,
        medium_term_context: str = "",
    ) -> dict[str, Any]:
        """外部写入一轮对话，驱动 Persona 状态层缓冲（→ dispatch RECORD_INTERACTION）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.RECORD_INTERACTION,
            payload={
                "question": question,
                "answer": answer,
                "medium_term_context": medium_term_context,
            },
        ))

    def search_memory(self, mode: str = "hybrid", **kwargs: Any) -> dict[str, Any]:
        """记忆检索（→ dispatch SEARCH）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.memory,
            action=MemoryAction.SEARCH,
            payload={"mode": mode, **kwargs},
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
                redis_client=self._redis_client,
                mysql_client=self._mysql_client,
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.memory_llm_aux_name,
                primary_llm=self._primary_llm,
                cfg=self._memory_cfg,
                soul_config=self._cfg,
            )
        return self._memory_handler

    def _ensure_life_handler(self) -> LifeHandler:
        if self._life_handler is None:
            self._ensure_drive_service()
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

    def _ensure_drive_service(self) -> DriveService:
        if self._drive_service is None:
            self._drive_service = DriveService(
                on_outbound_request=self._emit_drive_outbound,
            )
        return self._drive_service

    def _emit_drive_outbound(self, request: DriveOutboundRequest) -> None:
        for handler in self._drive_outbound_handlers:
            handler(request)

    def _wire_workers(self) -> None:
        from agent.soul.narrative_context_bridge import SoulNarrativeContextSupplier

        self._workers.register_life(self.life.api.worker)
        self.memory.set_worker(self._workers.memory)
        self.persona.set_worker(self._workers.persona)
        self.life.api.set_memory_port(self.memory.api)
        self.life.api.set_narrative_context_supplier(
            SoulNarrativeContextSupplier(self)
        )
        self.life.api.set_story_world_context_supplier(
            self._story_world_context_supplier
        )
