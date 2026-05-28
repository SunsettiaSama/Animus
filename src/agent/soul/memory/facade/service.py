from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.memory.domain import ActivationCue, EvolutionSource, GraphNode
from agent.soul.memory.emergence import Emergence
from agent.soul.memory.emergence.dispatcher import EmergenceQueryDispatcher
from agent.soul.memory.emergence.types import PointEmergenceResult
from agent.soul.memory.graph.networks.block import MemoryBlock
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.graph.networks.experience_block import read_experience_block
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.graph.networks.types import ExperienceKind
from agent.soul.memory.graph.networks.store.mysql.nodes import MySQLNodeStore
from agent.soul.memory.retriever import MemoryRetriever
from agent.soul.memory.rumination import RuminationService
from agent.soul.memory.sleep import SleepService
from agent.soul.memory.sleep.types import SleepResult
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService

if TYPE_CHECKING:
    from agent.soul.workers import DomainWorker


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
        nodes: MySQLNodeStore,
        memory_infra: MemoryInfraService | None = None,
        worker: DomainWorker | None = None,
        query_dispatcher: EmergenceQueryDispatcher | None = None,
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
        self._bind_enqueue()

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker
        self._bind_enqueue()

    def _bind_enqueue(self) -> None:
        enqueue = self._enqueue_write
        self.emergence.bind_enqueue(enqueue)
        if self._query_dispatcher is not None:
            self.emergence.spread.bind_query_submit(self._query_dispatcher.submit)
        self._event._enqueue_recall = enqueue

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

    def get_unit(self, unit_id: str) -> GraphNode | None:
        return self._nodes.get(unit_id)

    def ingest_experience(self, unit: ExperienceUnit) -> GraphNode | list[GraphNode]:
        block = read_experience_block(unit)
        if block.kind == ExperienceKind.anchor:
            written = self._social.ingest_anchor_experience(unit, block=block)
        else:
            written = self._event.ingest_event_experience(unit, block=block)
        for node in written if isinstance(written, list) else [written]:
            self.rumination.observe_node(node.id)
        return written

    def retract_experience(self, life_event_id: str) -> bool:
        return self._event.retract_experience(life_event_id)

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
        cue = ActivationCue(
            session_id=session_id,
            interactor_id=interactor_id or session_id,
            user_text=user_text,
            agent_text=agent_text,
            turn_index=turn_index,
        )
        self.emergence.query_point_async(cue)

    def on_point_emergence_ready(
        self,
        handler: Callable[[PointEmergenceResult], None],
    ) -> None:
        self.emergence.spread.on_point_ready(handler)

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
        source_units: list[GraphNode],
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
        return [s.render_line(max_content=100) for s in scored]

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

    def list_drift_units(self, *, month: str, anchor_unit_ids: list[str] | None = None, limit: int = 120) -> list[GraphNode]:
        target_month = month.strip()
        anchors = [uid for uid in (anchor_unit_ids or []) if uid]
        seen: set[str] = set()
        out: list[GraphNode] = []
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
