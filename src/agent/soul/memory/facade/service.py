from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.domain import ActivationCue, EvolutionSource
from agent.soul.memory.graph.base_node import BaseNode
from agent.soul.memory.emergence import Emergence
from agent.soul.memory.emergence.dispatcher import EmergenceQueryDispatcher
from agent.soul.memory.emergence.types import PointEmergenceResult
from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.facade.interactor_portrait import InteractorPortraitSpeakResult
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.retriever import MemoryRetriever
from agent.soul.memory.rumination import RuminationService
from agent.soul.memory.io.hub import MemoryIO
from agent.soul.memory.io.life import (
    LifeIODeps,
    LifeMemoryChannel,
    LifeMemoryIO,
)
from agent.soul.memory.io.session import (
    DialogueTurnInbound,
    SessionIODeps,
    SessionMemoryBuffer,
    SessionMemoryChannel,
    SessionSpeakIO,
    StaticPortraitInbound,
)
from agent.soul.memory.sleep import SleepService
from agent.soul.memory.sleep.types import SleepResult
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService

if TYPE_CHECKING:
    from agent.soul.workers import DomainWorker
    from infra.llm import BaseLLM


class MemoryService:
    """L6 门面：统一对外 API，内部管理 event / social 记忆网络。"""

    def __init__(
        self,
        social: SocialMemoryNetwork,
        event: EventMemoryNetwork,
        emergence: Emergence,
        rumination: RuminationService,
        sleep: SleepService,
        retriever: MemoryRetriever,
        cfg: MemoryServiceConfig,
        nodes: GraphNodeStore,
        memory_infra: MemoryInfraService | None = None,
        worker: DomainWorker | None = None,
        query_dispatcher: EmergenceQueryDispatcher | None = None,
        session_buffer: SessionMemoryBuffer | None = None,
        session_channel: SessionMemoryChannel | None = None,
        session_io: SessionSpeakIO | None = None,
        life_io: LifeMemoryIO | None = None,
        session_channels=None,
        llm: BaseLLM | None = None,
    ) -> None:
        self._social = social
        self._event = event
        self.emergence = emergence
        self.rumination = rumination
        self.sleep = sleep
        self._retriever = retriever
        self._cfg = cfg
        self._nodes = nodes
        self._memory_infra = memory_infra
        self._worker = worker
        self._query_dispatcher = query_dispatcher
        self._session_buffer = session_buffer
        if session_channel is not None:
            compression = session_channel
        elif session_buffer is not None:
            compression = SessionMemoryChannel(buffer=session_buffer)
        else:
            compression = SessionMemoryChannel()
        self._session_channel = compression
        io_deps = SessionIODeps(
            social=self._social,
            emergence=self.emergence,
            cfg=self._cfg,
            resolve_channel_interactor=self.resolve_channel_interactor,
            bind_session_channel=self.bind_session_channel,
            enqueue_write=self._enqueue_write,
        )
        if session_io is not None:
            self._session_io = session_io
        else:
            self._session_io = SessionSpeakIO(compression=compression, deps=io_deps)
        life_deps = LifeIODeps(
            event=self._event,
            social=self._social,
            rumination=self.rumination,
            session_compression=compression,
            enqueue_write=self._enqueue_write,
            agent_persona_narrative=self._agent_persona_narrative,
            llm=llm,
        )
        if life_io is not None:
            self._life_io = life_io
        else:
            self._life_io = LifeMemoryIO(
                channel=LifeMemoryChannel(life_deps),
                deps=life_deps,
            )
        self._io = MemoryIO(session=self._session_io, life=self._life_io)
        self._session_channels = session_channels
        self._agent_persona_provider: Callable[[], str] | None = None
        self._bind_enqueue()

    def set_agent_persona_provider(self, provider: Callable[[], str] | None) -> None:
        self._agent_persona_provider = provider

    def _agent_persona_narrative(self) -> str:
        if self._agent_persona_provider is None:
            return ""
        return self._agent_persona_provider().strip()

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker
        self._bind_enqueue()

    def _bind_enqueue(self) -> None:
        enqueue = self._enqueue_write
        self.emergence.bind_enqueue(enqueue)
        if self._query_dispatcher is not None:
            self.emergence.spread.bind_query_submit(self._query_dispatcher.submit)
        self._event._enqueue_recall = enqueue

    def enqueue_background(self, fn: Callable[[], None]) -> None:
        self._enqueue_write(fn)

    def _enqueue_write(self, fn: Callable[[], None]) -> None:
        if self._worker is not None:
            self._worker.enqueue(fn)
            return
        if self._cfg.async_ingest:
            threading.Thread(target=fn, daemon=True, name="memory-write").start()
        else:
            fn()

    def init_infra(self) -> None:
        if self._memory_infra is not None:
            self._memory_infra.warm_up()

    def get_unit(self, unit_id: str) -> BaseNode | None:
        return self._nodes.get(unit_id)

    @property
    def io(self) -> MemoryIO:
        return self._io

    @property
    def life_io(self) -> LifeMemoryIO:
        return self._life_io

    @property
    def life_port(self):
        """Life Experience 擢升端口（``life.io.memory`` → 正式落图）。"""
        from agent.soul.life.io.memory import LifeExperienceMemoryIO

        return LifeExperienceMemoryIO(self._life_io)

    @property
    def session_channel(self) -> SessionMemoryChannel:
        return self._session_channel

    @property
    def session_io(self) -> SessionSpeakIO:
        return self._session_io

    def evolve_core(
        self,
        interactor_id: str,
        *,
        delta: str,
        source: EvolutionSource = EvolutionSource.manual,
        evidence_ids: list[str] | None = None,
    ):
        return self._social.evolve_core(
            interactor_id,
            delta=delta,
            source=source,
            evidence_ids=evidence_ids,
        )

    def register_core_portrait(
        self,
        interactor_id: str,
        portrait: dict,
        *,
        agent_relation: str = "",
        display_name: str = "",
    ):
        return self._social.register_core_portrait(
            interactor_id,
            portrait,
            agent_relation=agent_relation,
            display_name=display_name,
        )

    def register_external_visitor(
        self,
        interactor_id: str,
        display_name: str,
        meta: dict | None = None,
    ) -> None:
        """外部账号创建时锚定 SocialCore 画像（供 Speak 对话者画像直达）。"""
        iid = interactor_id.strip()
        if not iid:
            raise ValueError("interactor_id 不能为空")
        name = display_name.strip()
        portrait: dict = {"name": name}
        raw_meta = meta or {}
        aliases = raw_meta.get("aliases")
        if isinstance(aliases, list) and aliases:
            portrait["background_facts"] = [
                f"别名：{a}" for a in aliases if str(a).strip()
            ]
        note = str(raw_meta.get("note", "")).strip()
        if note:
            portrait.setdefault("background_facts", [])
            if isinstance(portrait["background_facts"], list):
                portrait["background_facts"].append(note)
        self.register_core_portrait(
            iid,
            portrait,
            display_name=name,
        )

    def set_agent_relation(self, interactor_id: str, relation: str):
        return self._social.set_agent_relation(interactor_id, relation)

    def link_interactor_relation(
        self,
        interactor_id: str,
        other_interactor_id: str,
        *,
        label: str,
        content: str,
    ):
        return self._social.link_interactor_relation(
            interactor_id,
            other_interactor_id,
            label=label,
            content=content,
        )

    def recall_social(
        self,
        query: str,
        top_k: int | None = None,
        *,
        interactor_id: str = "",
    ) -> MemoryBlock:
        k = top_k if top_k is not None else self._cfg.recall_top_k
        return self._social.recall(query, k, interactor_id=interactor_id)

    def activate_async(self, cue: ActivationCue) -> None:
        self.emergence.expand_hot_async(cue)

    def expand_hot_activation(self, cue: ActivationCue):
        return self.emergence.spread.expand_hot_sync(cue)

    def query_point_activation(self, cue: ActivationCue):
        return self.emergence.spread.query_point_sync(cue)

    def query_point_async(self, cue: ActivationCue) -> None:
        self.emergence.query_point_async(cue)

    def request_speak_point_query(
        self,
        *,
        session_id: str,
        interactor_id: str,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self._session_io.submit_dialogue_turn(
            DialogueTurnInbound(
                session_id=session_id,
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
                interactor_id=interactor_id.strip(),
                channel_id=session_id.strip(),
                want_dynamic_event=True,
            )
        )

    def on_interactor_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None],
    ) -> None:
        self._session_io.on_dynamic_portrait_ready(handler)

    def resolve_channel_interactor(self, session_id: str) -> str:
        sid = session_id.strip()
        if not sid:
            return ""
        if self._session_channels is not None:
            bound = self._session_channels.get_interactor(sid)
            if bound:
                return bound
        return ""

    def bind_session_channel(self, session_id: str, interactor_id: str) -> None:
        sid = session_id.strip()
        iid = interactor_id.strip()
        if not sid or not iid:
            return
        if self._session_channels is not None:
            self._session_channels.bind(sid, iid)

    def request_speak_interactor_portrait(
        self,
        *,
        session_id: str,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
        hinted_interactor_id: str = "",
    ) -> None:
        self._session_io.submit_dialogue_turn(
            DialogueTurnInbound(
                session_id=session_id,
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
                interactor_id=hinted_interactor_id.strip(),
                channel_id=session_id.strip(),
                want_dynamic_portrait=True,
            )
        )

    def request_static_interactor_portrait(
        self,
        *,
        interactor_id: str,
        session_id: str = "",
        turn_index: int = 0,
    ) -> None:
        self._session_io.fetch_static_portrait(
            StaticPortraitInbound(
                interactor_id=interactor_id,
                session_id=session_id,
                turn_index=turn_index,
            )
        )

    def request_interactor_social_prefetch(
        self,
        *,
        session_id: str,
        interactor_id: str,
        turn_index: int = 0,
    ) -> None:
        from agent.soul.memory.io.session.request import InteractorPrefetchInbound

        self._session_io.submit_interactor_prefetch(
            InteractorPrefetchInbound(
                session_id=session_id.strip(),
                interactor_id=interactor_id.strip(),
                turn_index=turn_index,
            )
        )

    def submit_speak_keyword_query(
        self,
        *,
        session_id: str,
        turn_index: int,
        user_text: str,
        interactor_id: str = "",
        agent_text: str = "",
    ):
        from agent.soul.memory.io.session.request import KeywordQueryInbound

        return self._session_io.submit_keyword_query(
            KeywordQueryInbound(
                session_id=session_id.strip(),
                turn_index=turn_index,
                user_text=user_text,
                interactor_id=interactor_id.strip(),
                agent_text=agent_text,
            )
        )

    def on_interactor_social_ready(self, handler) -> None:
        self._session_io.on_interactor_social_ready(handler)

    def on_static_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None],
    ) -> None:
        self._session_io.on_static_portrait_ready(handler)

    def on_point_emergence_ready(
        self,
        handler: Callable[[PointEmergenceResult], None],
    ) -> None:
        self._session_io.on_dynamic_event_ready(handler)

    def get_point_emergence(self, session_id: str, turn_index: int):
        return self.emergence.get_point_result(session_id, turn_index)

    def trigger_speak_activation(
        self,
        *,
        session_id: str,
        interactor_id: str,
        user_text: str,
        agent_text: str = "",
        turn_index: int = 0,
    ) -> None:
        self.request_speak_point_query(
            session_id=session_id,
            interactor_id=interactor_id,
            turn_index=turn_index,
            user_text=user_text,
            agent_text=agent_text,
        )

    def get_activation_snapshot(self, session_id: str):
        return self.emergence.get_snapshot(session_id)

    def ruminate(self, unit_id: str, *, trigger: str, emotional_context: str):
        return self.rumination.ruminate(unit_id, trigger=trigger, emotional_context=emotional_context)

    def ingest_heartbeat(self, source_unit_id: str, trigger: str, emotional_context: str):
        return self.rumination.ingest_heartbeat(source_unit_id, trigger, emotional_context)

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        return self._event.ingest_narrative(
            source_unit_ids,
            chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def ingest_narrative_from_units(
        self,
        source_units: list[BaseNode],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        return self._event.ingest_narrative_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def forget_scan(self, threshold: float | None = None, dry_run: bool = False) -> list[str]:
        resolved = threshold if threshold is not None else self._cfg.forget_threshold
        event_ids = self._event.forget_scan(threshold, dry_run)
        social_ids = self._social.forget_scan(
            resolved,
            self._cfg.half_life_days,
            dry_run=dry_run,
        )
        return list(dict.fromkeys(event_ids + social_ids))

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        emotional_context: str = "",
    ) -> MemoryBlock:
        k = top_k if top_k is not None else self._cfg.recall_top_k
        return self._event.recall(query, k, emotional_context=emotional_context)

    def continuity_for_narrative(self, query: str) -> list[str]:
        q = query.strip()
        if not q:
            return []
        scored = self._retriever.continuity_for_narrative(
            q,
            top_k=self._cfg.narrative_continuity_top_k,
            candidate_k=self._cfg.narrative_continuity_candidate_k,
            min_relevance=self._cfg.narrative_continuity_min_relevance,
            min_final_score=self._cfg.narrative_continuity_min_final_score,
            max_score_gap=self._cfg.narrative_continuity_max_score_gap,
        )
        return [
            s.render_line(max_content=self._cfg.speak_memory_line_max_content)
            for s in scored
        ]

    def search(self, mode: str, **kwargs) -> list[dict]:
        from agent.soul.memory.graph.networks.store.codec import scored_to_dict
        from agent.soul.memory.domain import Valence

        m = mode.strip().lower()
        retriever = self._retriever
        if m in ("recent", "timeline"):
            scored = retriever.recent(
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                memory_type=kwargs.get("memory_type"),
            )
        elif m == "semantic":
            scored = retriever.semantic(query=str(kwargs["query"]), top_k=int(kwargs.get("top_k", 10)))
        elif m == "by_valence":
            valence = Valence(str(kwargs.get("valence", "neutral")))
            scored = retriever.by_valence(
                valence=valence,
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                emotion_hint=str(kwargs.get("emotion_hint", "")),
            )
        elif m == "by_field":
            valence_raw = kwargs.get("valence")
            valence = Valence(str(valence_raw)) if valence_raw else None
            scored = retriever.by_field(
                memory_type=kwargs.get("memory_type"),
                valence=valence,
                chapter=kwargs.get("chapter"),
                source_id=kwargs.get("source_id"),
                emotion_contains=kwargs.get("emotion_contains"),
                created_after=kwargs.get("created_after"),
                created_before=kwargs.get("created_before"),
                limit=int(kwargs.get("limit", 20)),
            )
        elif m in ("hybrid", "smart", "recall"):
            valence_raw = kwargs.get("valence")
            valence = Valence(str(valence_raw)) if valence_raw else None
            scored = retriever.hybrid(
                query=str(kwargs.get("query", "")),
                top_k=int(kwargs.get("top_k", self._cfg.recall_top_k)),
                valence=valence,
                memory_type=kwargs.get("memory_type"),
                w_relevance=float(kwargs.get("w_relevance", 0.6)),
                w_activation=float(kwargs.get("w_activation", 0.4)),
            )
        else:
            raise ValueError(f"unknown memory search mode: {mode!r}")
        return [scored_to_dict(s) for s in scored]

    def heartbeat_ruminate(self) -> dict:
        return self.rumination.heartbeat_ruminate()

    def run_sleep(
        self,
        *,
        tick_id: str = "",
        dry_run: bool = False,
        forget_threshold: float | None = None,
    ) -> SleepResult:
        return self.sleep.run(
            tick_id=tick_id,
            dry_run=dry_run,
            forget_threshold=forget_threshold,
        )

    def tick(self, snapshot):
        result = self.rumination.tick(snapshot)
        tid = getattr(snapshot, "tick_id", "") or ""
        result.buffer_candidates = self.collect_persona_cluster_signals(tick_id=tid)
        return result

    def collect_persona_cluster_signals(self, *, tick_id: str = "") -> list[dict]:
        clusters = self._retriever.persona_clusters(
            ltm_limit=self._cfg.persona_cluster_ltm_limit,
            min_cluster_size=self._cfg.persona_cluster_min_size,
            min_mass=self._cfg.persona_cluster_min_mass,
            top_k=self._cfg.persona_cluster_top_k,
            similarity_threshold=self._cfg.persona_cluster_similarity,
            min_span_days=self._cfg.persona_cluster_min_span_days,
            min_recurrence=self._cfg.persona_cluster_min_recurrence,
            min_cohesion=self._cfg.persona_cluster_min_cohesion,
            min_persona_score=self._cfg.persona_cluster_min_persona_score,
        )
        return [c.to_buffer_meta(tick_id=tick_id) for c in clusters]

    def fetch_persona_cluster(self, theme: str, *, unit_ids: list[str] | None = None, cluster_key: str = "") -> dict:
        material = self._retriever.fetch_persona_cluster(
            theme,
            unit_ids=unit_ids,
            cluster_key=cluster_key,
            top_k=self._cfg.persona_fetch_top_k,
            similarity_threshold=self._cfg.persona_fetch_similarity,
            ltm_limit=self._cfg.persona_cluster_ltm_limit,
        )
        return material.to_dict()

    def list_drift_units(self, *, month: str, anchor_unit_ids: list[str] | None = None, limit: int = 120) -> list[BaseNode]:
        target_month = month.strip()
        anchors = [uid for uid in (anchor_unit_ids or []) if uid]
        seen: set[str] = set()
        out: list[BaseNode] = []
        for unit in self._nodes.get_many(anchors):
            if unit.id in seen:
                continue
            seen.add(unit.id)
            out.append(unit)
        if len(out) < limit:
            for unit in self._nodes.list_recent(limit=max(limit * 2, limit)):
                if unit.id in seen:
                    continue
                if unit.created_at.strftime("%Y-%m") != target_month:
                    continue
                seen.add(unit.id)
                out.append(unit)
                if len(out) >= limit:
                    break
        return out[:limit]

    def drift_embedder(self):
        if self._memory_infra is None:
            return None
        return self._memory_infra.retriever_embedder()
