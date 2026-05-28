from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from agent.soul.life.experience.unit import ExperienceUnit
from agent.soul.memory.domain import FactualMemory, GraphNode, MemoryNetwork, ReconstructiveMemory, Valence
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, GraphNodeStore, VectorIndexPort
from agent.soul.memory.writer.narrative_writer import NarrativeWriter
from agent.soul.memory.writer.rumination_writer import RuminationWriter
from config.soul.memory.service_config import MemoryServiceConfig


@dataclass
class MemoryBlock:
    label: str = "记忆"
    entries: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.entries:
            return ""
        body = "\n".join(f"- {e}" for e in self.entries)
        return f"[{self.label}]\n{body}"

    def is_empty(self) -> bool:
        return not self.entries


class EventMemoryNetwork:
    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        query: QueryEngine,
        rumination: RuminationWriter,
        narrative: NarrativeWriter,
        cfg: MemoryServiceConfig,
        *,
        vectors: VectorIndexPort | None = None,
        on_written: Callable[[GraphNode], None] | None = None,
        enqueue_recall: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._nodes = nodes
        self._traversal = GraphTraversal(edges)
        self._query = query
        self._rumination = rumination
        self._narrative = narrative
        self._cfg = cfg
        self._vectors = vectors
        self._on_written = on_written
        self._enqueue_recall = enqueue_recall

    def ingest_experience(self, unit: ExperienceUnit) -> FactualMemory:
        vd = unit.feeling.valence_delta
        if vd > 0.15:
            valence = Valence.positive
        elif vd < -0.15:
            valence = Valence.negative
        else:
            valence = Valence.neutral

        fact = unit.situation.perception or unit.situation.narration or unit.action.content
        perception = unit.situation.narration or unit.situation.perception or unit.action.content
        raw_focus = perception or fact
        focus = raw_focus[:60] if raw_focus else unit.id[:8]

        mem = FactualMemory(
            focus=focus,
            fact=fact,
            perception=perception,
            emotion=unit.feeling.emotion_label,
            emotion_intensity=unit.feeling.salience,
            valence=valence,
            base_activation=max(0.3, unit.feeling.salience),
            life_event_id=unit.id,
        )
        self._nodes.put(mem)
        self._index(mem)
        return mem

    def retract_experience(self, life_event_id: str) -> bool:
        if not life_event_id:
            return False
        unit = self._nodes.get_by_life_event_id(life_event_id)
        if unit is None:
            return False
        self._nodes.archive(unit.id)
        if self._vectors is not None:
            self._vectors.remove(unit.id)
        return True

    def ruminate(
        self,
        node_id: str,
        *,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        source = self._nodes.get(node_id)
        if source is None:
            return None
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            return None
        ru = self._rumination.ruminate_from_source(source, trigger, emotional_context)
        if ru is not None:
            self._traversal.link_source_of(source.id, ru.id)
        return ru

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        *,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ):
        narrative = self._narrative.write(
            source_unit_ids=source_unit_ids,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )
        if narrative is not None:
            for sid in narrative.source_ids:
                self._traversal.link_weaves(narrative.id, sid)
        return narrative

    def recall(
        self,
        query: str,
        top_k: int,
        emotional_context: str = "",
    ) -> MemoryBlock:
        _ = emotional_context
        scored = self._query.hybrid(query=query, top_k=top_k)
        unit_ids = [s.unit.id for s in scored]
        if unit_ids and self._enqueue_recall is not None:
            self._enqueue_recall(lambda: self._on_recall_batch(unit_ids))
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="记忆参考", entries=entries)

    def forget_scan(self, threshold: float | None, dry_run: bool) -> list[str]:
        resolved = threshold if threshold is not None else self._cfg.forget_threshold
        archived = self._nodes.forget_scan(
            threshold=resolved,
            half_life_days=self._cfg.half_life_days,
            dry_run=dry_run,
            network=MemoryNetwork.event,
        )
        if not dry_run and self._vectors is not None:
            for uid in archived:
                self._vectors.remove(uid)
        return archived

    def tick_heartbeat(self, snapshot):
        from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

        tid = getattr(snapshot, "tick_id", "") or ""
        kws = [k for k in (getattr(snapshot, "attention_keywords", None) or []) if k]
        wandered = self._query.wander(n=2, focus_keywords=kws or None)
        wandered_ids = [s.unit.id for s in wandered]
        emotional_ctx = getattr(snapshot, "emotional_state", "") or ""

        ruminated_ids: list[str] = []
        for su in wandered:
            if su.unit.MEMORY_TYPE not in ("factual", "reconstructive"):
                continue
            ru = self.ruminate(
                su.unit.id,
                trigger=f"心跳漂移；情绪背景：{emotional_ctx or '平静'}",
                emotional_context=emotional_ctx,
            )
            if ru is not None:
                ruminated_ids.append(ru.id)

        narrative_triggered = False
        if wandered:
            avg_intensity = sum(s.unit.emotion_intensity for s in wandered) / len(wandered)
            if avg_intensity >= self._cfg.narrative_threshold:
                source_ids = [
                    s.unit.id
                    for s in wandered
                    if s.unit.MEMORY_TYPE in ("factual", "reconstructive")
                ]
                source_ids.extend(rid for rid in ruminated_ids if rid not in source_ids)
                if len(source_ids) >= 2:
                    narrative = self.ingest_narrative(
                        source_ids,
                        chapter="心跳叙事",
                        emotional_context=emotional_ctx,
                    )
                    narrative_triggered = narrative is not None

        if wandered:
            top = max(wandered, key=lambda s: s.unit.emotion_intensity)
            avg_intensity = sum(s.unit.emotion_intensity for s in wandered) / len(wandered)
            hint = ""
            if ruminated_ids:
                ru_unit = self._nodes.get(ruminated_ids[0])
                if ru_unit is not None:
                    hint = getattr(ru_unit, "reconstructed_fact", "")[:200]
            signal = EmotionalSignal(
                dominant_emotion=top.unit.emotion or "",
                dominant_valence=top.unit.valence,
                intensity=round(avg_intensity, 3),
                source_unit_ids=wandered_ids,
                narrative_hint=hint,
                tick_id=tid,
            )
        else:
            signal = EmotionalSignal(tick_id=tid)

        return MemoryHeartbeatResult(
            wandered_ids=wandered_ids,
            wandered_units=wandered,
            ruminated_ids=ruminated_ids,
            narrative_triggered=narrative_triggered,
            forgotten_count=0,
            signal=signal,
            tick_id=tid,
            buffer_candidates=[],
        )

    def _index(self, node: GraphNode) -> None:
        if self._on_written is not None:
            self._on_written(node)

    def _on_recall_batch(self, unit_ids: list[str]) -> None:
        for uid in unit_ids:
            self._nodes.on_recall(uid)
