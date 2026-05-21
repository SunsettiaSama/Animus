from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from agent.soul.memory.long_term.manager import LongTermMemoryManager
from agent.soul.memory.writer.rumination_writer import RuminationWriter
from agent.soul.memory.writer.narrative_writer import NarrativeWriter
from agent.soul.memory.unit import FactualMemory, MemoryUnit, NarrativeMemory, ReconstructiveMemory
from agent.soul.memory.embed_text import memory_unit_embed_text
from agent.soul.memory.retriever import MemoryRetriever
from config.soul.memory.service_config import MemoryServiceConfig
from infra.memory import MemoryInfraService

if TYPE_CHECKING:
    from infra.llm import BaseLLM
    from infra.db.mysql import MySQLClient
    from agent.soul.life.experience.unit import ExperienceUnit
    from agent.soul.workers import DomainWorker


@dataclass
class MemoryBlock:
    """检索结果的渲染块，可直接注入 prompt。"""

    label: str = "记忆"
    entries: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.entries:
            return ""
        body = "\n".join(f"- {e}" for e in self.entries)
        return f"[{self.label}]\n{body}"

    def is_empty(self) -> bool:
        return not self.entries


class MemoryService:
    """记忆子系统统一入口：MySQL 唯一记忆库 + infra 向量索引。"""

    def __init__(
        self,
        store: LongTermMemoryManager,
        rumination_writer: RuminationWriter,
        narrative_writer: NarrativeWriter,
        retriever: MemoryRetriever,
        cfg: MemoryServiceConfig,
        memory_infra: MemoryInfraService | None = None,
        worker: DomainWorker | None = None,
    ) -> None:
        self._store = store
        self._rumination_writer = rumination_writer
        self._narrative_writer = narrative_writer
        self._retriever = retriever
        self._cfg = cfg
        self._memory_infra = memory_infra
        self._worker = worker

    def set_worker(self, worker: DomainWorker | None) -> None:
        self._worker = worker

    def _enqueue_write(self, fn: Callable[[], None]) -> None:
        if self._worker is not None:
            self._worker.enqueue(fn)
            return
        if self._cfg.async_ingest:
            threading.Thread(target=fn, daemon=True, name="memory-write").start()
        else:
            fn()

    @classmethod
    def build(
        cls,
        llm: BaseLLM,
        mysql_client: MySQLClient,
        cfg: MemoryServiceConfig | None = None,
        memory_infra: MemoryInfraService | None = None,
    ) -> MemoryService:
        if cfg is None:
            cfg = MemoryServiceConfig.load_default()

        infra = memory_infra or MemoryInfraService.build()
        store = LongTermMemoryManager(mysql_client)
        store.init_schema()

        svc_holder: list[MemoryService] = []

        def _after_write(unit: MemoryUnit) -> None:
            if svc_holder:
                svc_holder[0]._schedule_index(unit)

        rumination_writer = RuminationWriter(
            llm,
            store,
            on_written=_after_write,
        )
        narrative_writer = NarrativeWriter(llm, store, on_written=_after_write)
        retriever = MemoryRetriever(
            store,
            recent_half_life_days=cfg.recent_half_life_days,
            half_life_days=cfg.half_life_days,
            embedder=infra.retriever_embedder(),
            vector_store=infra.retriever_vector_store(),
        )
        svc = cls(
            store,
            rumination_writer,
            narrative_writer,
            retriever,
            cfg,
            memory_infra=infra,
        )
        svc_holder.append(svc)
        return svc

    def init_infra(self) -> None:
        if self._memory_infra is not None:
            self._memory_infra.warm_up()

    def get_unit(self, unit_id: str) -> MemoryUnit | None:
        return self._store.get(unit_id)

    def ruminate(
        self,
        unit_id: str,
        *,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        source = self.get_unit(unit_id)
        if source is None:
            return None
        if source.MEMORY_TYPE not in ("factual", "reconstructive"):
            return None
        return self._rumination_writer.ruminate_from_source(
            source,
            trigger,
            emotional_context,
        )

    def ingest_heartbeat(
        self,
        source_unit_id: str,
        trigger: str,
        emotional_context: str,
    ) -> ReconstructiveMemory | None:
        return self.ruminate(
            source_unit_id,
            trigger=trigger,
            emotional_context=emotional_context,
        )

    def ingest_narrative(
        self,
        source_unit_ids: list[str],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory | None:
        return self._narrative_writer.write(
            source_unit_ids=source_unit_ids,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def ingest_narrative_from_units(
        self,
        source_units: list[MemoryUnit],
        chapter: str,
        persona_snapshot: str = "",
        emotional_context: str = "",
    ) -> NarrativeMemory:
        return self._narrative_writer.write_from_units(
            source_units=source_units,
            chapter=chapter,
            persona_snapshot=persona_snapshot,
            emotional_context=emotional_context,
        )

    def ingest_experience(self, unit: ExperienceUnit) -> FactualMemory:
        from agent.soul.memory.unit import Valence

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
        self._store.put(mem)
        self._schedule_index(mem)
        return mem

    def retract_experience(self, life_event_id: str) -> bool:
        if not life_event_id:
            return False
        unit = self._store.get_by_life_event_id(life_event_id)
        if unit is None:
            return False
        self._store.archive(unit.id)
        if self._memory_infra is not None and self._memory_infra.enabled:
            self._memory_infra.remove_unit(unit.id)
        return True

    def forget_scan(
        self,
        threshold: float | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        resolved = threshold if threshold is not None else self._cfg.forget_threshold
        archived = self._store.forget_scan(
            threshold=resolved,
            half_life_days=self._cfg.half_life_days,
            dry_run=dry_run,
        )
        if not dry_run and self._memory_infra is not None and self._memory_infra.enabled:
            for uid in archived:
                self._memory_infra.remove_unit(uid)
        return archived

    def recall(
        self,
        query: str,
        top_k: int | None = None,
        emotional_context: str = "",
    ) -> MemoryBlock:
        k = top_k if top_k is not None else self._cfg.recall_top_k
        scored = self._retriever.hybrid(
            query=query,
            top_k=k,
            w_relevance=0.6,
            w_activation=0.4,
        )
        unit_ids = [s.unit.id for s in scored]
        if unit_ids:
            self._enqueue_write(lambda: self._on_recall_batch(unit_ids))
        entries = [s.render_line() for s in scored]
        return MemoryBlock(label="记忆参考", entries=entries)

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
        from agent.soul.memory.unit import Valence

        m = mode.strip().lower()
        retriever = self._retriever

        if m in ("recent", "timeline"):
            scored = retriever.recent(
                limit=int(kwargs.get("limit", kwargs.get("top_k", 10))),
                memory_type=kwargs.get("memory_type"),
            )
        elif m == "semantic":
            scored = retriever.semantic(
                query=str(kwargs["query"]),
                top_k=int(kwargs.get("top_k", 10)),
            )
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
            raise ValueError(
                f"unknown memory search mode: {mode!r} "
                "(expected recent|semantic|by_valence|by_field|hybrid)"
            )

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

        ru = self.ruminate(
            su.unit.id,
            trigger="心跳反刍",
            emotional_context="",
        )
        out: dict = {
            "wandered": 1,
            "ruminated": 1 if ru is not None else 0,
            "unit_id": su.unit.id,
        }
        if ru is not None:
            out["reconstructed_id"] = ru.id
        return out

    def tick(self, snapshot) -> object:
        from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

        tid = getattr(snapshot, "tick_id", "") or ""
        kws = [k for k in (getattr(snapshot, "attention_keywords", None) or []) if k]

        wandered = self._retriever.wander(n=2, focus_keywords=kws or None)
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
                source_ids.extend(
                    rid for rid in ruminated_ids if rid not in source_ids
                )
                if len(source_ids) >= 2:
                    narrative = self._narrative_writer.write(
                        source_unit_ids=source_ids,
                        chapter="心跳叙事",
                        emotional_context=emotional_ctx,
                    )
                    narrative_triggered = narrative is not None

        buffer_candidates = self.collect_persona_cluster_signals(tick_id=tid)

        if wandered:
            top = max(wandered, key=lambda s: s.unit.emotion_intensity)
            avg_intensity = sum(s.unit.emotion_intensity for s in wandered) / len(wandered)
            hint = ""
            if ruminated_ids:
                ru_unit = self._store.get(ruminated_ids[0])
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
            buffer_candidates=buffer_candidates,
        )

    def collect_persona_cluster_signals(self, *, tick_id: str = "") -> list[dict]:
        """Persona 心跳采集：主题聚类 → buffer 元数据（不含正文）。"""
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

    def fetch_persona_cluster(
        self,
        theme: str,
        *,
        unit_ids: list[str] | None = None,
        cluster_key: str = "",
    ) -> dict:
        """Persona 月度 drift 回查：按主题与锚点 unit_ids 拉取共同事件材料。"""
        material = self._retriever.fetch_persona_cluster(
            theme,
            unit_ids=unit_ids,
            cluster_key=cluster_key,
            top_k=self._cfg.persona_fetch_top_k,
            similarity_threshold=self._cfg.persona_fetch_similarity,
            ltm_limit=self._cfg.persona_cluster_ltm_limit,
        )
        return material.to_dict()

    def list_drift_units(
        self,
        *,
        month: str,
        anchor_unit_ids: list[str] | None = None,
        limit: int = 120,
    ) -> list[MemoryUnit]:
        """Persona 漂移：返回目标月份 raw units（锚点优先，不含蒸馏）。"""
        target_month = month.strip()
        anchors = [uid for uid in (anchor_unit_ids or []) if uid]
        seen: set[str] = set()
        out: list[MemoryUnit] = []

        for unit in self._store.get_many(anchors):
            if unit.id in seen:
                continue
            seen.add(unit.id)
            out.append(unit)

        if len(out) < limit:
            scan_limit = max(limit * 2, limit)
            for unit in self._store.list_recent(limit=scan_limit):
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

    def _schedule_index(self, unit: MemoryUnit) -> None:
        if self._memory_infra is None or not self._memory_infra.enabled:
            return
        text = memory_unit_embed_text(unit)
        if not text.strip():
            return
        unit_id = unit.id
        self._enqueue_write(
            lambda: self._memory_infra.index_unit(unit_id, text)
        )

    def _on_recall_batch(self, unit_ids: list[str]) -> None:
        for uid in unit_ids:
            self._store.on_recall(uid)
