from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from config.agent.persona_config import PersonaConfig
from config.infra.db_config import DBConfig
from config.storage import StorageConfig
from config.soul.memory.service_config import MemoryServiceConfig
from infra.llm import BaseLLM
from infra.memory import MemoryInfraService

from config.soul.config import SoulConfig
from agent.soul.access import is_read_api_action
from agent.soul.heartbeat.bridge import MemoryHeartbeatResult
from agent.soul.heartbeat.evolution import new_heartbeat_tick_id
from agent.soul.heartbeat.orchestrator import HeartbeatOrchestrator
from agent.soul.life.experience.ingest.incident import IncidentIngestResult, LifeIncident
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
from .speak.responders.request_driven.composer import ComposeManagerConfig

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient
    from agent.soul.life.narrative_context import StoryWorldContextSupplier
    from agent.soul.ports import ExternalOpportunitySupplier
    from agent.soul.speak.io.outbound.stream import SpeakStreamPort
    from storyview.types import GMQuestion

logger = logging.getLogger(__name__)


class _MemoryNarrativeContextSupplier:
    def __init__(self, service) -> None:
        self._service = service

    def refresh(self, layer, purpose, *, query: str = "") -> None:
        _ = purpose
        q = query.strip()
        if not q:
            layer.update_context(continuity_memories=[])
            return
        lines = self._service.workers.memory.submit(
            lambda: self._service.memory.api.continuity_for_narrative(q)
        ).result()
        layer.update_context(continuity_memories=list(lines[:2]))


class SoulService:
    """Soul 顶层门面：组装 Persona / Memory / Life / Speak 各域处理器，统一对外 API 与 start/stop 生命周期。

    对外语义
    --------
    - ``dispatch(SoulRequest)``：统一请求入口，按域分发到 heartbeat / 各域 handler / 只读 query_* 通道。
    - ``query_*`` / ``search_memory`` / ``record_*``：HTTP API 快捷方法，内部同样走 dispatch。

    生命周期
    --------
    - ``stopped``：已停止，不可再启动。
    - ``idle`` / ``running``：允许只读 API action（白名单 ``access.READ_API_ACTIONS``）直接 dispatch。
    - ``running``：全部 action 均可 dispatch。
    """

    def __init__(
        self,
        *,
        life_dir: str,
        persona_cfg: PersonaConfig,
        mysql_client: MySQLClient | None = None,
        llm_service: LLMServicePort | None = None,
        primary_llm: BaseLLM | None = None,
        cfg: SoulConfig | None = None,
        memory_cfg: MemoryServiceConfig | None = None,
        memory_infra: MemoryInfraService | None = None,
        db_cfg: DBConfig | None = None,
        storage_backend: str | None = None,
        json_root: str | None = None,
    ) -> None:
        self._cfg = cfg or SoulConfig.load_default()
        self._memory_cfg = memory_cfg or MemoryServiceConfig.load_default()
        self._db_cfg = db_cfg or DBConfig.load_default()
        self._storage_backend = storage_backend or self._db_cfg.resolved_storage_backend()
        self._json_root = json_root or self._db_cfg.storage.json_root
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
        self._life_io_hub: Any = None
        self._speak_service: Any = None
        self._warm_spread_lines: list[str] = []
        self._warm_spread_unit_ids: list[str] = []
        self._account_service: Any = None
        self._story_world_context_supplier: StoryWorldContextSupplier | None = None
        self._story_service: Any = None
        self._story_port: Any = None
        self._external_opportunity_supplier: ExternalOpportunitySupplier | None = None
        self._presence_speak_bridge: Any = None
        self._presence_speak_wired = False
        self._agent_initiated_handlers: list[Any] = []

    @property
    def config(self) -> SoulConfig:
        return self._cfg

    @property
    def memory_config(self) -> MemoryServiceConfig:
        return self._memory_cfg

    @property
    def storage_backend(self) -> str:
        return self._storage_backend

    @property
    def storage_json_root(self) -> str:
        return self._json_root

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
    def life_io(self):
        self._ensure_life_io()
        return self._life_io_hub

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
        """挂接 Speak 流式适配器；可随时连接并冲刷积压。"""
        self.speak_outbound.bind_stream(port)

    def attach_speak_notify_port(self, port) -> None:
        """挂接 Speak notify 适配器（SSE 等）。"""
        self._ensure_speak_service().attach_notify_port(port)

    def deliver_speak_text(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> dict[str, Any]:
        """Speak 出站：直接投递文本（DELIVER 通道）。"""
        return self.speak_outbound.deliver_text(session_id, text, final=final)

    def start_dialogue_session(
        self,
        session_id: str = "tao",
        *,
        trigger: str = "user_message",
    ) -> dict[str, Any]:
        """打开或恢复同一条 Speak 生命线；仅 Registry 的物理 idle 可轮转。

        single-stream R4/R6.1：会话打开 = 在场周期，只恢复表演通道；
        旧编剧初始化链路已退役（v7），叙事冷启由 life/story 演化与
        角色 greeting 承接，剧情发起归 life/story。
        """
        self._require_running()
        speak = self._ensure_speak_service()
        opened = speak.session_manager.open(session_id, trigger=trigger)
        # Registry.open 已决定本次是否为新 generation；这里仅恢复生命线扫描。
        speak.bootstrap_proactive_loop(session_id)
        speak.mark_speak_wake(session_id)  # 握手门：进房即唤醒
        # 时间轴窗口注入（上下文唯一历史语义）：进房即刷新最近 k 条；
        # life 无在途事件时，附带 presence 待分享（近期期望分享的内容）。
        extra_lines: list[str] = []
        try:
            from agent.soul.wiring.story import ensure_story_runtime

            runtime = ensure_story_runtime(self)
            story_busy = bool(
                runtime.ledger.pending()
                or runtime.ledger.held()
                or runtime.pool.pending_landmark_ids()
            )
        except Exception:  # noqa: BLE001 — 剧情态不可得视为无事件
            story_busy = False
        if not story_busy:
            try:
                intents = self.presence.pop_top_share_intents(session_id, limit=2)
                extra_lines = [
                    f"她最近想分享：{(getattr(i, 'content', '') or getattr(i, 'topic', '')).strip()[:120]}"
                    for i in intents
                    if (getattr(i, 'content', '') or getattr(i, 'topic', '')).strip()
                ]
            except Exception:  # noqa: BLE001 — presence 缺席不阻塞注入
                extra_lines = []
        try:
            speak.inject_timeline_window(session_id, extra_lines=extra_lines)
        except Exception:  # noqa: BLE001 — 注入失败不阻塞会话打开
            pass
        return {
            "ok": True,
            "session_id": opened.session_id,
            "trigger": opened.trigger,
            "turn_count": speak.session_registry.current_turn_index(session_id),
            "generation": opened.generation,
            "started": opened.started,
            "temporal_rotated": opened.temporal_rotated,
        }

    def hydrate_speak_channel(self, session_id: str) -> str:
        """按 channel 找到绑定的交互者并同步给 Speak 会话（未绑定返回空串）。"""
        sid = session_id.strip()
        if not sid:
            return ""
        bound = ""
        if self.memory is not None and self.memory.api is not None:
            bound = self.memory.api.resolve_channel_interactor(sid)
        if bound:
            speak = self._ensure_speak_service()
            speak.bind_interactor(sid, bound)
        return bound

    def align_speak_visitor(self, session_id: str, channel_id: str) -> str:
        """WS 会话与 channel 对齐交互者：把绑定关系同步进 Speak session。"""
        sid = session_id.strip()
        cid = channel_id.strip() or sid
        if not sid:
            return ""
        iid = self.hydrate_speak_channel(cid)
        if iid:
            self._ensure_speak_service().bind_interactor(sid, iid)
            if self.memory is not None and self.memory.api is not None:
                self.memory.api.request_interactor_social_prefetch(
                    session_id=sid,
                    interactor_id=iid,
                )
        return iid

    @property
    def accounts(self):
        return self._ensure_account_service()

    def _ensure_account_service(self):
        if self._account_service is not None:
            return self._account_service
        from infra.accounts import AccountService

        def _on_registered(interactor_id: str, display_name: str, meta: dict) -> None:
            if self.memory is not None and self.memory.api is not None:
                self.memory.api.register_external_visitor(
                    interactor_id,
                    display_name,
                    meta,
                )

        self._account_service = AccountService.build(
            self._mysql_client,
            on_visitor_registered=_on_registered,
            storage_backend=self._storage_backend,
            json_root=self._json_root,
        )
        return self._account_service

    def bind_visitor(
        self,
        account_id: str,
        channel_id: str,
    ) -> dict[str, Any]:
        """WebUI 访客账号绑定到 channel：写 session 绑定并预热 Speak 画像上下文。"""
        self._require_running()
        accounts = self._ensure_account_service()
        account = accounts.get(account_id)
        if account is None:
            raise ValueError(f"Unknown account_id {account_id!r}")
        iid = account.interactor_id
        cid = channel_id.strip() or iid
        if self.memory is not None and self.memory.api is not None:
            self.memory.api.bind_session_channel(cid, iid)
        speak = self._ensure_speak_service()
        speak.bind_interactor(cid, iid)
        if self.memory is not None and self.memory.api is not None:
            self.memory.api.request_static_interactor_portrait(
                interactor_id=iid,
                session_id=cid,
                turn_index=0,
            )
            self.memory.api.request_interactor_social_prefetch(
                session_id=cid,
                interactor_id=iid,
            )
        return {
            "ok": True,
            "account_id": account.account_id,
            "interactor_id": iid,
            "channel_id": cid,
            "display_name": account.display_name,
        }

    def open_proactive_outbound(
        self,
        session_id: str,
        message: str,
        *,
        proactive_intent_id: str = "",
    ) -> dict[str, Any]:
        """主动开口（proactive outbound）：经 Life speak 通道投递，遵循 Speak lifecycle 约束。"""
        self._require_running()
        from agent.soul.life.io.speak import ProactiveOutboundInbound

        return self.life_io.speak.open_proactive_outbound(
            ProactiveOutboundInbound(
                session_id=session_id,
                message=message,
                proactive_intent_id=proactive_intent_id,
            ),
        )

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
        """记录一轮对话（speak 出口统一入口）：同步 presence 并写入 life/memory 体验。"""
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
        """会话收尾：驱动 life 与 presence 把本轮对话沉淀为 experience。"""
        self._require_running()
        from agent.soul.life.io.speak import DialogueSessionCloseInbound

        ack = self.life_io.speak.close_dialogue_session(
            DialogueSessionCloseInbound(session_id=session_id),
        )
        if not ack.ingested:
            return {"ok": ack.ok, "session_id": ack.session_id, "ingested": False}
        return {
            "ok": ack.ok,
            "session_id": ack.session_id,
            "ingested": True,
            "source": ack.source,
            "turn_index": ack.turn_index,
            "experience_id": ack.experience_id,
        }

    def finalize_speak_session(self, session_id: str = "tao") -> dict[str, Any]:
        """Speak 会话 rotate（=reset_context + close + generation rotate + start）。"""
        self._require_running()
        speak = self._ensure_speak_service()
        result = speak.session_manager.holder.finalize_session(
            session_id,
            reason="manual",
            note="manual reset",
        )
        return {
            "ok": True,
            "session_id": result.session_id,
            "reason": result.reason,
            "generation": result.generation,
            "ingested": result.ingested,
            "experience_id": result.experience_id,
            "turn_index": result.turn_index,
            "source": result.source,
            "notes": list(result.notes),
        }

    def speak_turn(
        self,
        user_text: str,
        *,
        session_id: str = "tao",
        stream: bool = False,
        mode: str = "inbound",
        pipeline: str | None = None,
    ):
        """Speak 回合兼容入口：统一转到 L0 speak_run_turn。"""
        return self.speak_run_turn(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            responder=pipeline,
        )

    def speak_run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = True,
        mode: str = "inbound",
        record: bool = True,
        responder: str | None = None,
    ):
        """Speak 回合：转发 SpeakService.run_turn（L0 入口，勿直接 dispatch）。"""
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行：state={self._state!r}")
        _speak = self._ensure_speak_service()
        _speak.mark_speak_wake(session_id)  # 握手门：用户发言即唤醒
        return _speak.run_turn(
            session_id,
            user_text,
            stream=stream,
            mode="proactive" if mode == "proactive" else "inbound",
            record=record,
            responder=responder,
        )

    def speak_submit_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = True,
        mode: str = "inbound",
        record: bool = True,
        responder: str | None = None,
    ) -> dict[str, Any]:
        """Speak 用户输入入队；忙碌时打断出站，由后续 run_turn 把原文直达角色。"""
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行：state={self._state!r}")
        speak = self._ensure_speak_service()
        speak.stamp_user_ingress(session_id, user_text)
        submit = speak.session_manager.submit_user_input(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            record=record,
            responder=responder,
        )
        return {
            "queued": bool(submit.queued),
            "interrupt": bool(submit.interrupt),
            "responder": responder,
            "notes": list(submit.notes),
            "director_notified": {"notified": False, "reason": "user_direct_to_character"},
        }

    def speak_is_pushing(self, session_id: str) -> bool:
        if self._speak_service is None:
            return False
        return self._speak_service.session_manager.is_pushing(session_id)

    def speak_is_busy(self, session_id: str) -> bool:
        if self._speak_service is None:
            return False
        return self._speak_service.is_busy(session_id)

    def attach_character_work_port(self, port) -> None:
        """把角色求助口接到 worker 轻量执行（严格分流，不写进角色提示词）。"""
        self._ensure_speak_service().attach_character_work_port(port)

    def speak_on_typing_pulse(
        self,
        session_id: str,
        *,
        typing: bool,
        draft: str = "",
    ) -> dict[str, object]:
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行（state={self._state!r}）。")
        _speak = self._ensure_speak_service()
        _speak.mark_speak_wake(session_id)  # 握手门：输入脉冲即唤醒
        return _speak.on_typing_pulse(
            session_id,
            typing=typing,
            draft=draft,
        )

    def speak_set_delivery_mode(self, mode: str) -> None:
        if self._speak_service is not None:
            self._speak_service.set_delivery_mode(mode)

    def flush_speak_async_delivery(self, session_id: str) -> None:
        if self._speak_service is not None:
            self._speak_service.flush_async_delivery(session_id)

    def speak_director_snapshot(self, session_id: str) -> dict[str, object]:
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行（state={self._state!r}）。")
        return self._ensure_speak_service().director_snapshot(session_id)

    def speak_set_typing_idle_ms(self, session_id: str, *, ms: int = 3000) -> int:
        if self._state != "running":
            raise RuntimeError(f"SoulService is not running (state={self._state!r})")
        runtime = self._ensure_speak_service().session_manager.queues._runtime(session_id)
        runtime.typing_idle_ms = 5000 if ms >= 5000 else 3000
        return runtime.typing_idle_ms

    def speak_enqueue_brew(
        self,
        session_id: str,
        text: str,
        *,
        reason: str = "soul",
        flush_if_idle: bool = True,
    ) -> dict[str, object]:
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行（state={self._state!r}）。")
        return self._ensure_speak_service().enqueue_proactive_brew(
            session_id,
            text,
            reason=reason,
            flush_if_idle=flush_if_idle,
        )

    def speak_session_trace_cache(
        self,
        session_id: str,
        *,
        turn_index: int | None = None,
    ) -> dict[str, object]:
        if self._state != "running" or self._speak_service is None:
            raise RuntimeError(f"Soul Speak 未初始化（state={self._state!r}）。")
        return self._speak_service.session_trace_cache(
            session_id,
            turn_index=turn_index,
        )

    @property
    def speak_initialized(self) -> bool:
        return self._speak_service is not None

    def reset_presence_affect(self, session_id: str = "tao") -> None:
        """清空 Presence 快变情绪（affect），回到基线状态。"""
        self.presence.reset_affect(session_id)

    def speak_generate(
        self,
        user_text: str,
        *,
        session_id: str = "tao",
        system: str = "",
        context: str = "",
        stream: bool = False,
    ) -> dict[str, Any]:
        """Speak LLM 直生成（不经 compose 编排，可注入 system/context 覆盖）。"""
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

    def _answer_gm_question_with_speak(
        self,
        question: GMQuestion,
        *,
        session_id: str = "tao",
    ) -> str:
        speak = self._ensure_speak_service()
        choices = "\n".join(
            f"- {choice}"
            for choice in question.choices
            if str(choice).strip()
        )
        choice_mode = "可自由回应，不必局限于选项。"
        if not question.open_choice:
            choice_mode = "必须从给定选项中选择或用同义短句回答。"
        context_parts = [
            f"【故事主持问题】\n{question.question.strip()}",
            f"【本拍线索】\n{question.cue.strip() or '（无）'}",
        ]
        if question.stakes.strip():
            context_parts.append(f"【利害】\n{question.stakes.strip()}")
        if choices.strip():
            context_parts.append(f"【可选行动】\n{choices}")
        if question.constraints.strip():
            context_parts.append(f"【限制】\n{question.constraints.strip()}")
        context_parts.append(f"【选择模式】\n{choice_mode}")
        system = (
            "你是 Soul，正在故事场景中回应主持人的问题。\n"
            "规则：\n"
            "- 只输出 Soul 的一句回答或行动意图，不解释、不复述主持问题\n"
            "- 使用第一人称「我」\n"
            "- 20~80 字，具体说明选择、意图或补充动作\n"
            "- 避免元叙事和技术实现语境；不要提命运骰或概率\n"
            "- 不要输出 JSON、markdown、标签或编号"
        )
        result = speak.generate(
            session_id,
            "\n\n".join(context_parts),
            system=system,
            context="",
        )
        text = re.sub(r"\s+", " ", result.text).strip()
        text = re.sub(r"^[-*]\s*", "", text).strip()
        if not text:
            if question.choices:
                return str(question.choices[0]).strip()
            return "我先观察。"
        return text[:120]

    def set_embedding_port(self, port: EmbeddingPort | None) -> None:
        """注入外部 embedding 端口。"""
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
        """注册 speak 出站后的 presence 回写钩子：speak 完成后同步 presence。"""
        self.speak_outbound.register_after_presence(handler)

    def register_agent_initiated_handler(self, handler: Any) -> None:
        """Agent 主动发起事件的回调注册（供 WebUI SSE 订阅）。"""
        self._agent_initiated_handlers.append(handler)

    def set_story_world_context_supplier(
        self,
        supplier: StoryWorldContextSupplier | None,
    ) -> None:
        """注入故事世界上下文供给器：life 写体验时用它补充场景/世界观背景。"""
        self._story_world_context_supplier = supplier
        self._ensure_life_handler()
        self.life.api.set_story_world_context_supplier(supplier)

    def set_external_opportunity_supplier(
        self,
        supplier: ExternalOpportunitySupplier | None,
    ) -> None:
        """注入外部机会供给器：心跳扫描时判断是否值得发起主动交互。"""
        self._external_opportunity_supplier = supplier

    def ingest_presence_event(
        self,
        event: PresenceEvent,
        *,
        line_open: bool = False,
        proactive_intent_id: str = "",
    ) -> PresenceIngestResult:
        """处理一条 presence 边界事件（presence.interface 协议）。"""
        self._require_running()
        result = self.presence.interface.boundary(
            event,
            context=PresenceContext(
                line_open=line_open,
                proactive_intent_id=proactive_intent_id,
            ),
        )
        if result.impulse_discharge is not None:
            self._handle_presence_speak_trigger(
                event.session_id,
                self._speak_request_from_discharge(
                    result.impulse_discharge,
                    session_id=event.session_id,
                ),
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
        """Presence 周期：边界事件/期望扫描/speak 触发，可选 life 叙事；presence 叙事入 LifeExperienceStack。"""
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
                    self._handle_presence_speak_trigger(
                        session_id,
                        self._speak_request_from_discharge(
                            ing.impulse_discharge,
                            session_id=session_id,
                        ),
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
        """当前 Presence 自我叙事（由 PresenceService 组装）。"""
        self._ensure_presence_service()
        return self.presence.compose_self_narrative(session_id)

    def initiate_presence_conversation(
        self,
        session_id: str = "tao",
        *,
        source: str = "initiate_conversation",
        wait_reply: bool = True,
    ) -> dict[str, Any]:
        """主动发起一次对话：宣泄冲动 + 期望检查，达到条件时触发 speak 主动开口。"""
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
            speak_result = self._handle_presence_speak_trigger(session_id, request)
            return {
                "ok": bool(speak_result.get("ok")),
                "session_id": session_id,
                "speak": speak_result,
                "presence_narrative": request.presence_narrative,
            }

        return self._workers.presence.submit(_run).result()

    def ingest_presence_incident(self, incident: LifeIncident) -> IncidentIngestResult:
        """Life 事件转 experience unit：presence 知晓后写入 experience stack。"""
        self._require_running()
        self._ensure_experience_pipeline()
        return self.experience.ingest_incident(incident, salience=incident.salience)

    def seed_session_warm_spread(self, session_id: str) -> None:
        sid = session_id.strip()
        if not sid or not self._warm_spread_unit_ids:
            return
        self._ensure_speak_service().seed_warm_spread(
            sid,
            lines=list(self._warm_spread_lines),
            unit_ids=list(self._warm_spread_unit_ids),
        )

    def arm_enter_greeting(self, session_id: str) -> None:
        self._ensure_speak_service().arm_enter_greeting(session_id)

    def ensure_screenwriter_init(self, session_id: str) -> None:
        self._ensure_speak_service().ensure_screenwriter_init(session_id)

    def speak_is_live_warm(self, session_id: str) -> bool:
        return self._ensure_speak_service().is_live_warm(session_id)

    def speak_bootstrap_proactive_loop(self, session_id: str) -> None:
        self._ensure_speak_service().bootstrap_proactive_loop(session_id)

    def speak_resolve_create_ui(
        self,
        delivery_id: str,
        *,
        accepted: bool,
        channel_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        return self._ensure_speak_service().resolve_outbound_create_ui(
            delivery_id,
            accepted=accepted,
            channel_id=channel_id,
            session_id=session_id,
        )

    def speak_acknowledge_proactive(
        self,
        delivery_id: str,
        *,
        session_id: str = "",
        channel_id: str = "",
    ) -> bool:
        return self._ensure_speak_service().acknowledge_outbound_proactive(
            delivery_id,
            session_id=session_id,
            channel_id=channel_id,
        )

    def speak_enter_page_context(
        self,
        session_id: str,
        *,
        page_key: str,
        messages: list[dict] | None = None,
        lines: list[str] | None = None,
    ) -> dict:
        return self._ensure_speak_service().enter_page_context(
            session_id,
            page_key=page_key,
            messages=messages,
            lines=lines,
        )

    def cancel_enter_greeting(self, session_id: str) -> None:
        if self._speak_service is not None:
            self._speak_service.cancel_enter_greeting(session_id)

    def _on_memory_infra_ready(self) -> None:
        """embedding 后台预热完成后的回调；stop 之后不再预热 spread。"""
        if self._state == "stopped":
            return
        self._prime_warm_spread()

    def _prime_warm_spread(self) -> None:
        from agent.soul.memory.domain import ActivationCue

        cue = ActivationCue(
            session_id="__warm__",
            user_text="最近怎么样 想起以前的事 前几天做过什么 心情还好吗",
            interactor_id="",
        )
        result = self.memory.api.expand_hot_activation(cue)
        self._warm_spread_lines = list(result.lines)
        self._warm_spread_unit_ids = list(result.unit_ids)

    def start(self) -> None:
        if self._state == "running":
            return
        if self._state == "stopped":
            raise RuntimeError("SoulService 已 stop，不可重新启动；请新建实例后再 start")

        self._ensure_memory_handler()
        self.memory.api.init_infra(on_ready=self._on_memory_infra_ready)
        self._ensure_life_handler()
        self._ensure_persona_handler()
        self._wire_workers()
        self._sync_presence_expectation_from_persona()
        self._sync_agent_persona_context()
        self._workers.start_all()
        self._ensure_speak_service().start()
        self._ensure_account_service()

        self.life.api.load_profile()
        hb = self._ensure_heartbeat()
        hb.start_evolution_worker()
        self._start_core_heartbeat()
        self._state = "running"
        logger.info("[SoulService] started - life_dir=%s", self._life_dir)

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
        """绑定外部 HeartbeatModule（可选）：Soul 尚未 start() 时也可先接线。"""
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
        """接入 runtime 调度引擎：供 checklist 编排使用；未接时由 Soul 自身 tick 驱动。"""
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
            raise RuntimeError(f"SoulService 已停止（state={self._state!r}）。")
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
        """跑一次 wander：memory tick 驱动 presence rumination/affect 与 life 体验。"""
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
        from agent.soul.speak.responders.request_driven.orchestrator.blocks.persona import (
            collect_persona_layer,
        )

        injected = collect_persona_layer(persona_snap=persona_snap)
        persona_profile = injected.dialogue.strip()
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
        """手动触发一次记忆睡眠整理（遗忘扫描 + 聚类重建 + 反刍喂料 + 缓冲衰减）。"""
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

    def run_evolve_upcoming_landmarks(self, within_sec: float = 3600.0) -> list[dict]:
        """预约轴提前演化（T-1h）：重 LLM，offload 到 life worker。"""
        self._require_running()
        return self._workers.life.submit(
            lambda: self.life.api.evolve_upcoming_landmarks(within_sec=within_sec)
        ).result()

    def run_tellable_landmarks(self) -> list[dict]:
        """已演化未开口地标（echo 重出稿素材）：纯读手账，零 LLM。"""
        self._require_running()
        return self._workers.life.submit(
            lambda: self.life.api.done_landmarks_for_tell()
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
        speak_result: dict[str, Any] | None = None
        if discharge is not None:
            speak_result = self._handle_presence_speak_trigger(
                session_id,
                self._speak_request_from_discharge(discharge, session_id=session_id),
            )
            triggered = bool(speak_result.get("ok"))
        return {
            "checked": True,
            "opportune": True,
            "triggered": triggered,
            "session_id": session_id,
            "speak": speak_result,
        }

    def run_expectation_scan(self, session_id: str = "tao") -> dict[str, Any]:
        """跑一次期望扫描（spresence 饱和检查）：达标时由 Soul 触发主动 speak。"""
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
            speak_result = self._handle_presence_speak_trigger(session_id, request)
            detail["speak_source"] = request.source
            detail["speak"] = speak_result
            if speak_result.get("deferred"):
                detail["deferred"] = True
        return detail

    def run_presence_wake(self, session_id: str = "tao", *, force: bool = False) -> dict[str, Any]:
        """手动唤醒 Presence FSM（可强制）：注入唤醒上下文并返回迁移叙事。"""
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
        """进入睡眠：Presence 迁移到 asleep，并联动一次记忆睡眠整理。"""
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
            summary_parts.append("核心特质：" + "、".join(str(t) for t in traits[:5]))
        style = str(profile.get("style", "")).strip()
        if style:
            summary_parts.append(f"行为风格：{style}")
        return WakeContext(
            agent_name=str(profile.get("name", "")),
            persona_summary="\n".join(summary_parts),
            self_narrative=str(concept.get("narrative", "")),
            timezone=tz,
        )

    def execute_plan_landmark(self) -> dict[str, Any]:
        """由 life-worker 规划一条里程碑：先查窗口配额，再 compose + 计划写入。"""
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

    # ── 对外查询 API：HTTP / WebUI 只读通道；以下方法均为 dispatch 的快捷封装 ─────────────────────────────────────

    def query_persona(self, *, session_id: str = "tao") -> dict[str, Any]:
        """查询 Persona 快照 + Presence 状态与自我叙事（供 WebUI 诊断面板）。"""
        snap = self.get_persona_snapshot(session_id=session_id)
        self._ensure_presence_service()
        snap["presence"] = self.presence.snapshot(session_id).state.to_dict()
        snap["presence_affect"] = snap["presence"]["affect"]
        snap["presence_self_narrative"] = self.presence_self_narrative(session_id)
        return snap

    def get_persona_snapshot(self, *, session_id: str = "tao") -> dict[str, Any]:
        """Persona 只读快照（profile / self_concept / persona_distill 等切片）。

        Speak 常用 ``persona_distill.slices.dialogue`` 对话切片，其余域请勿整包引用。
        """
        _ = session_id
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.GET_SNAPSHOT,
        ))

    def reload_persona_profile(self) -> dict[str, Any]:
        """从磁盘 persona_dir 重读 profile / built_profile / self_concept。"""
        result = self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.RELOAD_PROFILE,
        ))
        if self._state == "running":
            self._sync_agent_persona_context()
        return result

    def rebuild_persona_profile(
        self,
        *,
        preserve_self_concept: bool = False,
    ) -> dict[str, Any]:
        """LLM 基于 raw profile 重建画像与自我概念（可选保留 self_concept）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.persona,
            action=PersonaAction.REBUILD_PROFILE,
            payload={"preserve_self_concept": preserve_self_concept},
        ))

    def search_memory(self, mode: str = "hybrid", **kwargs: Any) -> dict[str, Any]:
        """记忆检索快捷入口（走 dispatch SEARCH）。"""
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
        """事件记忆 recall（走 dispatch RECALL）。"""
        payload: dict[str, Any] = {"query": query, "emotional_context": emotional_context}
        if top_k is not None:
            payload["top_k"] = top_k
        return self.dispatch(SoulRequest(
            domain=SoulDomain.memory,
            action=MemoryAction.RECALL,
            payload=payload,
        ))

    def query_life_chronicle(self, *, days: int = 7, tail: int = 50) -> list[dict[str, Any]]:
        """Life 近期 Chronicle 查询（走 dispatch RECENT_CHRONICLE）。"""
        return self.dispatch(SoulRequest(
            domain=SoulDomain.life,
            action=LifeAction.RECENT_CHRONICLE,
            payload={"days": days, "tail": tail},
        ))

    def query_life_hot(self, *, hours: int | None = None) -> list[dict[str, Any]]:
        """Life 热存储查询（走 dispatch HOT_STORAGE）。"""
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
            raise RuntimeError(f"SoulService 已停止（state={self._state!r}）。")
        if is_read_api_action(request.domain, request.action):
            return
        self._require_running()

    def _require_running(self) -> None:
        if self._state != "running":
            raise RuntimeError(f"SoulService 未运行（state={self._state!r}），请先调用 start()")

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
                storage_backend=self._storage_backend,
                json_root=self._json_root,
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
            from agent.soul.speak.io.experience_port import SoulSpeakExperiencePort

            director_aux = __import__("os").environ.get(
                "REACT_SPEAK_DIRECTOR_LLM",
                "speak_director",
            ).strip() or "speak_director"
            self._speak_handler = SpeakHandler(
                get_speak_service=self._ensure_speak_service,
                experience=SoulSpeakExperiencePort(self),
                llm_service=self._llm_service,
                llm_aux_name=self._cfg.speak_llm_aux_name,
                director_aux_name=director_aux,
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
            self._ensure_life_io()
        return self._experience_pipeline

    def _ensure_life_io(self):
        from agent.soul.life.io import LifeExperienceMemoryIO, LifeIOHub, LifeSpeakIO

        self._ensure_experience_pipeline()
        if self._life_io_hub is None:
            memory_io = None
            if self.memory is not None and self.memory.api is not None:
                memory_io = LifeExperienceMemoryIO(self.memory.api.life_io)
            self._life_io_hub = LifeIOHub(
                speak=LifeSpeakIO(self._experience_pipeline),
                memory=memory_io,
            )
        return self._life_io_hub

    def _reset_speak_session_context(self, session_id: str) -> None:
        if self._speak_service is not None:
            self._speak_service.reset_context(session_id)

    def _ensure_speak_service(self):
        if self._speak_service is None:
            from agent.soul.speak import SpeakService
            from agent.soul.speak.io.outbound.life import (
                SpeakLifeLifecycleBridge,
                SpeakLifeOutboundBridge,
            )
            from agent.soul.speak.llm.director_engine import SpeakDirectorLLMEngine
            from agent.soul.speak.llm.engine import SpeakLLMEngine
            from agent.soul.handlers.api._llm import resolve_module_llm

            self._ensure_life_io()
            life_speak = self.life_io.speak
            speak_life_out = SpeakLifeOutboundBridge(life_speak)
            speak_life_lc = SpeakLifeLifecycleBridge(
                life_speak,
                reset_context=self._reset_speak_session_context,
            )

            flush_mode = self._cfg.speak_stream_flush_mode
            if flush_mode not in {"segment", "token_batch"}:
                flush_mode = "segment"

            director_aux = __import__("os").environ.get(
                "REACT_SPEAK_DIRECTOR_LLM",
                "speak_director",
            ).strip() or "speak_director"
            director_llm = resolve_module_llm(
                self._llm_service,
                director_aux,
                self._primary_llm,
            )

            self._speak_service = SpeakService(
                presence=self._presence_service,
                persona=self,
                life_outbound=speak_life_out,
                life_lifecycle=speak_life_lc,
                llm_engine=SpeakLLMEngine(
                    resolve_module_llm(
                        self._llm_service,
                        self._cfg.speak_llm_aux_name,
                        self._primary_llm,
                    )
                ),
                director_llm_engine=SpeakDirectorLLMEngine(director_llm),
                flush_mode=flush_mode,  # type: ignore[arg-type]
                share_threshold=self._cfg.speak_share_proactive_threshold,
                session_idle_sec=self._cfg.speak_session_idle_sec,
                semantic_distance_threshold=self._cfg.speak_session_semantic_distance_threshold,
                embedder=self.resolve_embedding_port(),
                context_distill_chunk_size=self._cfg.speak_context_distill_chunk_size,
                memory_turn_gap=self._memory_cfg.memory_turn_proximity_max,
                keyword_wait_ms=self._memory_cfg.speak_compose_keyword_wait_ms,
                memory_budget=self._memory_cfg.speak_compose_memory_budget,
                portrait_wait_ms=self._memory_cfg.speak_compose_memory_wait_ms,
                compose_manager_enabled=bool(
                    getattr(self._cfg, "speak_compose_manager_enabled", True)
                ),
                compose_manager_config=ComposeManagerConfig(
                    enabled=bool(
                        getattr(self._cfg, "speak_compose_manager_enabled", True)
                    ),
                    director_memory_intervene_max=int(
                        getattr(self._cfg, "speak_director_memory_intervene_max", 1)
                    ),
                ),
                story_pool_dir=StorageConfig().story_pool_dir,
            )
            from agent.soul.memory.io.session import CompressionBlockInbound, DialogueCompressionBlock

            def _on_compression_block(block: DialogueCompressionBlock) -> None:
                interactor_id = (block.interactor_id or "").strip()
                if not interactor_id:
                    interactor_id = (
                        self._speak_service.session_registry.get_bound_interactor(
                            block.session_id
                        )
                        or ""
                    ).strip()

                def _task() -> None:
                    from agent.soul.memory.facade.persona_context import (
                        build_agent_persona_narrative,
                    )

                    pipeline = self._ensure_experience_pipeline()
                    llm = resolve_module_llm(
                        self._llm_service,
                        self._cfg.speak_llm_aux_name,
                        self._primary_llm,
                    )
                    persona = build_agent_persona_narrative(self.get_persona_snapshot())
                    pipeline.ingest_compression_block(
                        block,
                        interactor_id=interactor_id,
                        llm=llm,
                        agent_persona_narrative=persona,
                    )

                if self.memory is not None and self.memory.api is not None:
                    self.memory.api.enqueue_background(_task)
                else:
                    _task()

            if self._speak_service._context is not None:

                def _resolve_distill_interactor(session_id: str) -> str:
                    bound = self._speak_service.session_registry.get_bound_interactor(
                        session_id
                    )
                    if bound:
                        return bound.strip()
                    if self.memory is not None and self.memory.api is not None:
                        return (
                            self.memory.api.resolve_channel_interactor(session_id) or ""
                        ).strip()
                    return ""

                self._speak_service._context.set_resolve_interactor(
                    _resolve_distill_interactor
                )
                self._speak_service._context.set_on_block_ready(_on_compression_block)
                from agent.soul.memory.facade.persona_context import (
                    build_speak_dialogue_persona_anchor,
                )

                self._speak_service._context.set_agent_persona_provider(
                    lambda: build_speak_dialogue_persona_anchor(
                        self.get_persona_snapshot()
                    ),
                )

            from agent.soul.memory.io.session import DialogueTurnInbound
            from agent.soul.speak.io.inbound.memory import (
                InteractorPortraitPullResult,
                InteractorPortraitRequest,
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
                self.memory.api.session_io.submit_dialogue_turn(
                    DialogueTurnInbound(
                        session_id=request.session_id,
                        turn_index=request.turn_index,
                        user_text=request.user_text,
                        agent_text=request.agent_text,
                        interactor_id=request.interactor_id,
                        channel_id=request.session_id,
                        want_dynamic_event=True,
                    )
                )

            def _keyword_query_for_speak(request) -> None:
                from agent.soul.speak.io.inbound.memory import KeywordQueryRequest

                assert isinstance(request, KeywordQueryRequest)
                result = self.memory.api.submit_speak_keyword_query(
                    session_id=request.session_id,
                    turn_index=request.turn_index,
                    user_text=request.user_text,
                    interactor_id=request.interactor_id,
                    agent_text=request.agent_text,
                )
                if result.unit_ids:
                    self._speak_service.session_manager.enqueue_memory_result(
                        result.session_id,
                        turn_index=result.turn_index,
                        lines=list(result.lines),
                        unit_ids=list(result.unit_ids),
                        source="keyword",
                    )

            def _pull_similar_for_speak(
                session_id: str,
                turn_index: int,
                *,
                keyword_wait_ms: int = 200,
                budget: int = 5,
                merge_ratio=None,
                user_text: str = "",
            ) -> SimilarMemoryPullResult:
                consumed = self._speak_service.session_manager.pull_memory_for_compose(
                    session_id,
                    turn_index,
                    keyword_wait_ms=keyword_wait_ms,
                    budget=budget,
                    merge_ratio=merge_ratio,
                    user_text=user_text,
                )
                inject_turn = (
                    consumed.inject_turn_indices[0]
                    if consumed.inject_turn_indices
                    else turn_index
                )
                return SimilarMemoryPullResult(
                    inject=SimilarMemoryBlock(
                        turn_index=inject_turn,
                        lines=list(consumed.inject_lines),
                        unit_ids=list(consumed.inject_unit_ids),
                    ),
                    spilled=SimilarMemoryBlock(
                        turn_index=0,
                        lines=list(consumed.spilled_lines),
                        unit_ids=list(consumed.spilled_unit_ids),
                    ),
                    social_prefetch_lines=list(consumed.social_prefetch_lines),
                    social_prefetch_unit_ids=list(consumed.social_prefetch_unit_ids),
                    warm_spread_lines=list(consumed.warm_spread_lines),
                    warm_spread_unit_ids=list(consumed.warm_spread_unit_ids),
                    merge_ratio=consumed.merge_ratio,
                    keyword_wait_ms=consumed.keyword_wait_ms,
                    sources=list(consumed.sources),
                )

            def _on_interactor_social_ready(result) -> None:
                self._speak_service.session_manager.set_social_prefetch(
                    result.session_id,
                    lines=list(result.lines),
                    unit_ids=list(result.unit_ids),
                )

            def _on_point_emergence_ready(result) -> None:
                if not result.associative_ready:
                    return
                unit_ids = result.merged_unit_ids()
                if not unit_ids:
                    return
                self._speak_service.session_manager.enqueue_memory_result(
                    result.session_id,
                    turn_index=result.turn_index,
                    lines=result.merged_lines(),
                    unit_ids=unit_ids,
                    source="emergence",
                    ready=True,
                )

            self._speak_service.attach_memory_recall(_recall_for_speak)
            self._speak_service.attach_memory_point_query(_point_query_for_speak)
            self._speak_service.attach_memory_keyword_query(_keyword_query_for_speak)
            self._speak_service.attach_memory_pull_similar(_pull_similar_for_speak)

            def _compose_memory_search_for_speak(
                session_id: str,
                query_text: str,
                limit: int,
                hint: str,
            ):
                from agent.soul.speak.responders.request_driven.composer.ports.adapters import (
                    units_from_search_hits,
                )

                _ = session_id
                cap = max(1, int(limit))
                q = query_text.strip()
                if hint == "random" or not q:
                    hits = self.memory.api.search("recent", limit=cap)
                else:
                    hits = self.memory.api.search("hybrid", query=q, top_k=cap)
                return units_from_search_hits(hits, limit=cap)

            self._speak_service.attach_compose_memory_search(_compose_memory_search_for_speak)
            embedder = self.resolve_embedding_port()
            if embedder is not None:
                self._speak_service.attach_compose_embedder(embedder)

            def _landmark_briefs_for_speak():
                return self.life.api.upcoming_landmarks(within_sec=3600.0)

            self._speak_service.attach_landmark_port(_landmark_briefs_for_speak)

            def _portrait_query_for_speak(request: InteractorPortraitRequest) -> None:
                self.memory.api.session_io.submit_dialogue_turn(
                    DialogueTurnInbound(
                        session_id=request.session_id,
                        turn_index=request.turn_index,
                        user_text=request.user_text,
                        agent_text=request.agent_text,
                        interactor_id=request.hinted_interactor_id,
                        channel_id=request.session_id,
                        want_dynamic_portrait=True,
                    )
                )

            def _on_interactor_portrait_ready(result) -> None:
                if result.interactor_id.strip():
                    iid = result.interactor_id.strip()
                    sid = result.session_id.strip()
                    self._speak_service.bind_interactor(sid, iid)
                    self.memory.api.bind_session_channel(sid, iid)
                portrait_text = result.portrait_text.strip()
                if not portrait_text and result.interactor_id.strip():
                    from agent.soul.speak.responders.request_driven.orchestrator.guidance.memory import (
                        render_interactor_portrait_for_prompt,
                    )

                    portrait_text = render_interactor_portrait_for_prompt(
                        name=result.display_name,
                        core_traits=list(result.core_traits),
                        portrait_body=result.portrait_body,
                        agent_relation=result.agent_relation,
                        recent_impression=result.recent_impression,
                    )
                self._speak_service.session_manager.enqueue_interactor_portrait(
                    result.session_id,
                    turn_index=result.turn_index,
                    interactor_id=result.interactor_id,
                    portrait_text=portrait_text,
                )

            def _pull_portrait_for_speak(
                session_id: str,
                turn_index: int,
                wait_ms: int,
            ) -> InteractorPortraitPullResult:
                consumed = self._speak_service.session_manager.pull_portrait_for_compose(
                    session_id,
                    turn_index,
                    wait_ms=wait_ms,
                )
                return InteractorPortraitPullResult(
                    portrait_text=consumed.portrait_text,
                    interactor_id=consumed.interactor_id,
                    turn_index=consumed.inject_turn_index or turn_index,
                )

            self._speak_service.attach_memory_portrait_query(_portrait_query_for_speak)
            self._speak_service.attach_memory_pull_portrait(_pull_portrait_for_speak)
            self.memory.api.session_io.on_dynamic_portrait_ready(
                _on_interactor_portrait_ready
            )
            self.memory.api.session_io.on_static_portrait_ready(
                _on_interactor_portrait_ready
            )
            self.memory.api.session_io.on_dynamic_event_ready(_on_point_emergence_ready)
            self.memory.api.on_interactor_social_ready(_on_interactor_social_ready)
        if self._story_port is not None:
            self._speak_service.set_story_port(
                self._story_port,
                lambda: self.life.api.profile.resolved_world_id(),
            )
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
            self._presence_service = PresenceService(
                life_dir=self._life_dir,
                timezone=tz,
            )
            if llm is not None:
                self._presence_service.bind_unit_distill_llm(llm)
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
            reason = f"{reason}\n\n当前自我叙事：\n{narrative}" if reason else narrative
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
            reason = f"{reason}\n\n当前自我叙事：\n{narrative}" if reason else narrative
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

    def _ensure_presence_speak_io(self) -> None:
        if self._presence_speak_wired:
            return
        self._ensure_presence_service()
        self._ensure_speak_service()
        from agent.soul.presence.io.hub import PresenceIOHub
        from agent.soul.presence.io.speak import PresenceSpeakIO
        from agent.soul.speak.io.inbound.presence import SpeakPresenceInboundBridge

        self._presence_speak_bridge = SpeakPresenceInboundBridge(
            self,
            on_agent_initiated=self._notify_agent_initiated,
        )
        self._presence_service.bind_io(
            PresenceIOHub(speak=PresenceSpeakIO(self._presence_speak_bridge)),
        )
        self._ensure_speak_service().io.inbound.attach_presence(
            self._presence_speak_bridge,
        )
        self._presence_speak_wired = True

    def _notify_agent_initiated(self, payload: dict[str, Any]) -> None:
        for handler in self._agent_initiated_handlers:
            handler(payload)

    def _candidate_speak_session_ids(self, session_id: str) -> list[str]:
        base = session_id.strip() or "tao"
        ids: list[str] = []
        for sid in (base, "webui"):
            if sid and sid not in ids:
                ids.append(sid)
        channel = self.hydrate_speak_channel(base)
        if channel and channel not in ids:
            ids.append(channel)
        if self._speak_service is not None:
            bound = self._speak_service.session_registry.get_bound_interactor(base)
            if bound and bound not in ids:
                ids.append(bound)
        return ids

    def _find_active_speak_session_id(self, session_id: str) -> str | None:
        """只认 Speak 当前仍活跃的对话；历史 Life 记账不算活跃会话。"""
        self._ensure_speak_service()
        speak = self._speak_service
        for sid in self._candidate_speak_session_ids(session_id):
            if speak.session_manager.has_active_dialogue(sid):
                return sid
        return None

    def _speak_has_active_dialogue(self, session_id: str) -> bool:
        return self._find_active_speak_session_id(session_id) is not None

    def _intents_from_speak_request(
        self,
        request: SpeakRequest,
        *,
        limit: int = 2,
    ) -> list:
        package = request.package
        if package is not None and package.entries:
            ordered = sorted(package.entries, key=lambda item: item.salience, reverse=True)
            return list(ordered[: max(1, limit)])
        return self.presence.pop_top_share_intents(
            request.session_id.strip() or "tao",
            limit=limit,
        )

    def _defer_share_to_active_session(
        self,
        presence_session_id: str,
        *,
        limit: int = 2,
        intents: list | None = None,
    ) -> dict[str, Any]:
        """把 presence 侧的 1–2 条分享意图顺延到活跃 speak 会话（延迟而非丢弃）。"""
        presence_sid = presence_session_id.strip() or "tao"
        speak_sid = self._find_active_speak_session_id(presence_sid) or presence_sid
        resolved = intents
        if resolved is None:
            resolved = self.presence.pop_top_share_intents(presence_sid, limit=limit)
        else:
            resolved = list(resolved[: max(1, limit)])
        if not resolved:
            return {
                "ok": False,
                "deferred": False,
                "session_id": speak_sid,
                "presence_session_id": presence_sid,
                "reason": "share queue empty",
            }
        speak = self._ensure_speak_service()
        injected = speak.session_manager.inject_deferred_share_intents(speak_sid, resolved)
        director_notes = speak.ingest_deferred_share_for_director(speak_sid, resolved)
        from agent.soul.speak.io.inbound.compose.request import ComposePrepareRequest

        speak.io.inbound.compose.request_prepare(
            ComposePrepareRequest(session_id=speak_sid),
        )
        return {
            "ok": True,
            "deferred": True,
            "session_id": speak_sid,
            "presence_session_id": presence_sid,
            "injected": injected,
            "director": director_notes,
        }

    def _request_has_share_content(self, request: SpeakRequest) -> bool:
        package = request.package
        if package is not None and package.entries:
            return True
        sid = request.session_id.strip() or "tao"
        return self.presence.share_queue_size(sid) > 0

    def _handle_presence_speak_trigger(
        self,
        session_id: str,
        request: SpeakRequest,
    ) -> dict[str, Any]:
        if not self._request_has_share_content(request):
            return {
                "ok": False,
                "session_id": session_id.strip() or request.session_id,
                "reason": "share queue empty",
                "skipped_proactive": True,
                "source": request.source,
            }
        # Agent 想 speak：允许创建新窗口向外抛出，不再因活跃对话 defer 掉
        return self._emit_presence_speak(request)

    def _emit_presence_speak(self, request: SpeakRequest) -> dict[str, Any]:
        self._ensure_presence_speak_io()
        speak = self._ensure_speak_service()
        channel_id = (
            speak.session_registry.get_bound_interactor(request.session_id) or ""
        ).strip() or request.session_id.strip()
        ack = self.presence.io.speak.initiate_from_speak_request(
            request,
            channel_id=channel_id,
        )
        result = {
            "ok": ack.ok,
            "session_id": ack.session_id,
            "channel_id": ack.channel_id,
            "message": ack.message,
            "wait_reply": request.wait_reply,
            "append": ack.append,
            "source": request.source,
            "expectation": request.expectation.value,
            "blocked": ack.blocked,
            "agent_initiated": ack.agent_initiated,
            "proactive_intent_id": ack.proactive_intent_id,
            "ui": dict(ack.ui),
        }
        if not ack.ok and ack.reason:
            result["reason"] = ack.reason
        for handler in self.speak_outbound._after_presence_handlers:
            handler(request)
        return result

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
        """Memory.persona_clusters 主题信号 → 转发给 PersonaService.record_cluster_signals。"""
        if not candidates:
            return {"ok": True, "applied": 0, "signal_ids": []}
        return self._workers.persona.submit(
            lambda: self.persona.service.record_cluster_signals(candidates)
        ).result()

    def _sync_presence_expectation_from_persona(self) -> dict[str, Any] | None:
        if not self._persona_cfg.enabled:
            from agent.soul.presence.init_expectation import apply_expectation_tier
            from agent.soul.presence.init_expectation.tier import parse_expectation_tier, ExpectationTier

            tier = parse_expectation_tier(self._persona_cfg.expectation_tier_override)
            if tier is None:
                tier = ExpectationTier.medium
            apply_expectation_tier(tier)
            if self._speak_service is not None:
                self._speak_service.refresh_share_expectation_thresholds()
            return {"tier": tier.value, "source": "persona_disabled_override"}
        self._ensure_persona_handler()
        detail = self.persona.service.sync_presence_expectation(
            embedder=self.resolve_embedding_port(),
            tier_override=self._persona_cfg.expectation_tier_override,
        )
        if self._speak_service is not None:
            self._speak_service.refresh_share_expectation_thresholds()
        return detail

    def _sync_agent_persona_context(self) -> None:
        from agent.soul.memory.facade.persona_context import build_agent_persona_narrative

        self._sync_presence_expectation_from_persona()
        snap = self.get_persona_snapshot()
        narrative = build_agent_persona_narrative(snap)

        self._ensure_memory_handler()
        self.memory.api.set_agent_persona_provider(
            lambda: build_agent_persona_narrative(self.get_persona_snapshot()),
        )

        if self._life_handler is not None:
            self.life.api.sync_agent_persona_narrative(narrative)

        if self._speak_service is not None and self._speak_service._context is not None:
            from agent.soul.memory.facade.persona_context import (
                build_speak_dialogue_persona_anchor,
            )

            self._speak_service._context.set_agent_persona_provider(
                lambda: build_speak_dialogue_persona_anchor(self.get_persona_snapshot()),
            )

    def _ensure_story_service(self):
        """Storyview 通道暂时关闭：不启动 StoryService，不接线 StoryPort。

        等 storyview 场面不再幻觉、世界观落地后，再恢复本方法，
        并重新 register_story / speak.set_story_port / life.set_story_port。
        """
        return None

    def _wire_workers(self) -> None:
        self._workers.register_life(self.life.api.worker)
        self.memory.set_worker(self._workers.memory)
        self.persona.set_worker(self._workers.persona)
        self.persona.set_memory_port(self.memory.api)
        self.persona.set_embedder(self.memory.api.drift_embedder())
        from agent.soul.life.io import LifeExperienceMemoryIO

        life_memory = LifeExperienceMemoryIO(self.memory.api.life_io)
        self.life.api.set_memory_port(life_memory)
        self.life.api.set_narrative_context_supplier(
            _MemoryNarrativeContextSupplier(self)
        )
        # Storyview 端口暂不接线；地标/意外不跑 GM。
        profile = self.life.api.load_profile()
        world_id = profile.resolved_world_id()
        if not profile.world_id.strip():
            profile.world_id = world_id
            self.life.api.save_profile()
        self.life.api.bind_story_world(world_id)
        from storyview import PlaceholderWorldContext

        self.set_story_world_context_supplier(PlaceholderWorldContext())
        self._ensure_experience_pipeline()
        self._experience_pipeline.orchestrator._memory_port = life_memory
        self._experience_pipeline.life.set_memory_port(life_memory)
        self._ensure_life_io()
        if self._life_io_hub is not None:
            self._life_io_hub.memory = life_memory
