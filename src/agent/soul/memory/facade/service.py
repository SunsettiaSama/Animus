from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

from agent.soul.memory.activation.service import ActivationService
from agent.soul.memory.domain import ActivationCue, EvolutionSource, GraphNode
from agent.soul.memory.facade.adapters.life_ingest import LifeIngestAdapter
from agent.soul.memory.facade.adapters.speak_activation import SpeakActivationAdapter
from agent.soul.memory.networks.event.service import EventMemoryNetwork, MemoryBlock
from agent.soul.memory.networks.social.service import SocialMemoryNetwork
from agent.soul.memory.retriever import MemoryRetriever
from agent.soul.memory.store.mysql.nodes import MySQLNodeStore
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService

if TYPE_CHECKING:
    from agent.soul.life.experience.sources import ExperienceSource
    from agent.soul.workers import DomainWorker

from agent.soul.life.experience.unit import ExperienceUnit


class MemoryService:
    """L6 门面：薄路由至 social / event / activation 子系统。"""

    def __init__(
        self,
        social: SocialMemoryNetwork,
        event: EventMemoryNetwork,
        activation: ActivationService,
        life_ingest: LifeIngestAdapter,
        speak_activation: SpeakActivationAdapter,
        retriever: MemoryRetriever,
        cfg: MemoryServiceConfig,
        nodes: MySQLNodeStore,
        memory_infra: MemoryInfraService | None = None,
        worker: DomainWorker | None = None,
    ) -> None:
        self.social = social
        self.event = event
        self.activation = activation
        self._life_ingest = life_ingest
        self._speak_activation = speak_activation
        self._retriever = retriever
        self._cfg = cfg
        self._nodes = nodes
        self._memory_infra = memory_infra
        self._worker = worker
        self._bind_enqueue()

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker
        self._bind_enqueue()

    def _bind_enqueue(self) -> None:
        enqueue = self._enqueue_write
        self.activation._enqueue = enqueue
        self.event._enqueue_recall = enqueue

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

    def ingest_experience(self, unit: ExperienceUnit):
        if unit.source == ExperienceSource.interaction.value:
            self._life_ingest.ingest_experience(unit)
            return None
        return self._event.ingest_experience(unit)

    def retract_experience(self, life_event_id: str) -> bool:
        return self._life_ingest.retract_experience(life_event_id)

    def evolve_core(
        self,
        interactor_id: str,
        *,
        delta: str,
        source: EvolutionSource = EvolutionSource.manual,
        evidence_ids: list[str] | None = None,
    ):
        return self.social.evolve_core(
            interactor_id,
            delta=delta,
            source=source,
            evidence_ids=evidence_ids,
        )

    def activate_async(self, cue: ActivationCue) -> None:
        self.activation.activate_async(cue)

    def trigger_speak_activation(
        self,
        *,
        session_id: str,
        interactor_id: str,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self._speak_activation.trigger(
            session_id=session_id,
            interactor_id=interactor_id,
            user_text=user_text,
            agent_text=agent_text,
        )

    def get_activation_snapshot(self, session_id: str):
        return self.activation.get_snapshot(session_id)

    def ruminate(self, unit_id: str, *, trigger: str, emotional_context: str):
        return self.event.ruminate(unit_id, trigger=trigger, emotional_context=emotional_context)

    def ingest_heartbeat(self, source_unit_id: str, trigger: str, emotional_context: str):
        return self.ruminate(source_unit_id, trigger=trigger, emotional_context=emotional_context)

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        return self.event.ingest_narrative(
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
        from agent.soul.memory.writer.narrative_writer import NarrativeWriter

        writer: NarrativeWriter = self.event._narrative
        return writer.write_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def forget_scan(self, threshold: float | None = None, dry_run: bool = False) -> list[str]:
        return self.event.forget_scan(threshold, dry_run)

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        emotional_context: str = "",
    ) -> MemoryBlock:
        k = top_k if top_k is not None else self._cfg.recall_top_k
        return self.event.recall(query, k, emotional_context=emotional_context)

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
        from agent.soul.memory.codec import scored_to_dict
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
        wandered = self._retriever.wander(n=1)
        if not wandered:
            return {"wandered": 0, "ruminated": 0}
        su = wandered[0]
        if su.unit.MEMORY_TYPE not in ("factual", "reconstructive"):
            return {
                "wandered": 1,
                "ruminated": 0,
                "skipped_type": su.unit.MEMORY_TYPE,
                "unit_id": su.unit.id,
            }
        ru = self.ruminate(su.unit.id, trigger="心跳反刍", emotional_context="")
        out = {"wandered": 1, "ruminated": 1 if ru is not None else 0, "unit_id": su.unit.id}
        if ru is not None:
            out["reconstructed_id"] = ru.id
        return out

    def tick(self, snapshot):
        result = self.event.tick_heartbeat(snapshot)
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
