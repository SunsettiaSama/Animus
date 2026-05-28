from __future__ import annotations

from agent.soul.memory.domain import MemoryNetwork, ReconstructiveMemory
from agent.soul.memory.emotion_intensity import node_emotion_intensity
from agent.soul.memory.graph.query import QueryEngine
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphEdgeStore, GraphNodeStore
from agent.soul.memory.rumination.buffer import RuminationBuffer
from agent.soul.memory.rumination.sample import gaussian_pick
from agent.soul.memory.rumination.skill import RuminationSkill
from agent.soul.memory.rumination.types import RuminationConfig, RuminationSkillContext
from agent.soul.memory.rumination.writer import RuminationWriter
from agent.soul.memory.emergence.spread import SpreadActivationService
from agent.soul.memory.graph.networks.writer import NarrativeWriter
from config.soul.memory.service_config import MemoryServiceConfig


class RuminationService:
    """反刍：buffer 准入 → 高斯抽样 → skill 编排 →（可选）写回图。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        edges: GraphEdgeStore,
        query: QueryEngine,
        writer: RuminationWriter,
        narrative: NarrativeWriter,
        spread: SpreadActivationService,
        cfg: MemoryServiceConfig,
        *,
        rumination_cfg: RuminationConfig | None = None,
    ) -> None:
        self._nodes = nodes
        self._traversal = GraphTraversal(edges)
        self._query = query
        self._writer = writer
        self._narrative = narrative
        self._spread = spread
        self._cfg = cfg
        self._rumination_cfg = rumination_cfg or RuminationConfig()
        self._buffer = RuminationBuffer(self._rumination_cfg)
        self._skill = RuminationSkill(
            nodes,
            spread,
            writer,
            self._traversal,
            cfg=self._rumination_cfg,
        )

    @property
    def buffer(self) -> RuminationBuffer:
        return self._buffer

    def observe_node(self, node_id: str, *, tick_id: str = "") -> bool:
        node = self._nodes.get(node_id)
        if node is None:
            return False
        return self._buffer.observe(node, tick_id=tick_id)

    def feed_high_emotion_node(
        self,
        node_id: str,
        *,
        tick_id: str = "",
        emotion_threshold: float | None = None,
    ) -> bool:
        node = self._nodes.get(node_id)
        if node is None:
            return False
        return self._buffer.observe_high_emotion(
            node,
            tick_id=tick_id,
            emotion_threshold=emotion_threshold,
        )

    def consolidate_from_sleep(
        self,
        *,
        tick_id: str = "",
        scan_limit: int = 500,
        emotion_threshold: float | None = None,
    ) -> tuple[int, list[str]]:
        """睡眠整理后：扫描存活 event 记忆，高情绪者入反刍 buffer。"""
        threshold = (
            emotion_threshold
            if emotion_threshold is not None
            else self._rumination_cfg.emotion_threshold
        )
        self._buffer.reconcile(self._nodes)
        candidates = self._nodes.list_all(limit=scan_limit, network=MemoryNetwork.event)
        fed_ids: list[str] = []
        for node in candidates:
            if node.MEMORY_TYPE not in ("factual", "reconstructive"):
                continue
            if self._buffer.observe_high_emotion(
                node,
                tick_id=tick_id,
                emotion_threshold=threshold,
            ):
                fed_ids.append(node.id)
        return len(fed_ids), fed_ids

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
        ru = self._writer.ruminate_from_source(source, trigger, emotional_context)
        if ru is not None:
            self._traversal.link_source_of(source.id, ru.id)
        return ru

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

    def run_skill(
        self,
        node_id: str,
        *,
        trigger: str,
        emotional_context: str = "",
        tick_id: str = "",
        persona_profile: str = "",
    ):
        ctx = RuminationSkillContext(
            node_id=node_id,
            trigger=trigger,
            emotional_context=emotional_context,
            tick_id=tick_id,
            persona_profile=persona_profile,
        )
        return self._skill.run(ctx)

    def heartbeat_ruminate(self) -> dict:
        picked = self._pick_from_buffer(tick_id="", trigger="心跳反刍")
        if picked is None:
            return {"wandered": 0, "ruminated": 0, "buffer_size": len(self._buffer)}
        skill_result = picked["skill"]
        out = {
            "wandered": 1,
            "ruminated": 1 if skill_result.ran else 0,
            "unit_id": picked["node_id"],
            "buffer_size": len(self._buffer),
            "skill": skill_result.detail,
        }
        if skill_result.reconstructive_id:
            out["reconstructed_id"] = skill_result.reconstructive_id
        return out

    def tick(self, snapshot):
        from agent.soul.heartbeat.bridge import EmotionalSignal, MemoryHeartbeatResult

        tid = getattr(snapshot, "tick_id", "") or ""
        kws = [k for k in (getattr(snapshot, "attention_keywords", None) or []) if k]
        emotional_ctx = getattr(snapshot, "emotional_state", "") or ""
        persona_profile = getattr(snapshot, "persona_profile", "") or ""

        pool = self._scan_pool(focus_keywords=kws or None)
        self._buffer.ingest_pool(pool, tick_id=tid)
        self._buffer.reconcile(self._nodes)

        picked = self._pick_from_buffer(
            tick_id=tid,
            trigger=f"心跳漂移；情绪背景：{emotional_ctx or '平静'}",
            emotional_context=emotional_ctx,
            persona_profile=persona_profile,
        )

        wandered_ids: list[str] = [n.id for n in pool[:2]]
        wandered_units = self._query.wander(n=2, focus_keywords=kws or None)
        ruminated_ids: list[str] = []
        narrative_triggered = False
        picked_id = ""
        skill_detail: dict = {}

        if picked is not None:
            picked_id = picked["node_id"]
            skill_result = picked["skill"]
            skill_detail = skill_result.detail
            if skill_result.overwritten or skill_result.reconstructive_id:
                ruminated_ids.append(skill_result.node_id)
            if picked_id not in wandered_ids:
                wandered_ids = [picked_id, *wandered_ids]

        signal = self._build_signal(
            picked_id=picked_id,
            wandered_units=wandered_units,
            emotional_ctx=emotional_ctx,
            tick_id=tid,
        )

        return MemoryHeartbeatResult(
            wandered_ids=wandered_ids,
            wandered_units=wandered_units,
            ruminated_ids=ruminated_ids,
            narrative_triggered=narrative_triggered,
            forgotten_count=0,
            signal=signal,
            tick_id=tid,
            buffer_candidates=[],
            rumination_buffer_size=len(self._buffer),
            rumination_picked_id=picked_id,
            rumination_skill=skill_detail,
        )

    def _scan_pool(self, *, focus_keywords: list[str] | None):
        seen: set[str] = set()
        out = []
        for su in self._query.wander(n=3, focus_keywords=focus_keywords):
            if su.unit.id in seen:
                continue
            seen.add(su.unit.id)
            out.append(su.unit)
        for node in self._nodes.list_recent(
            limit=self._rumination_cfg.pool_scan_limit,
            network=MemoryNetwork.event,
        ):
            if node.id in seen:
                continue
            if node.MEMORY_TYPE not in ("factual", "reconstructive"):
                continue
            seen.add(node.id)
            out.append(node)
        return out

    def _pick_from_buffer(
        self,
        *,
        tick_id: str,
        trigger: str,
        emotional_context: str = "",
        persona_profile: str = "",
    ) -> dict | None:
        entries = self._buffer.entries()
        if not entries:
            return None
        entry = gaussian_pick(entries, sigma=self._rumination_cfg.gaussian_sigma)
        if entry is None:
            return None
        skill_result = self.run_skill(
            entry.node_id,
            trigger=trigger,
            emotional_context=emotional_context,
            tick_id=tick_id,
            persona_profile=persona_profile,
        )
        return {"node_id": entry.node_id, "entry": entry, "skill": skill_result}

    def _build_signal(self, *, picked_id: str, wandered_units, emotional_ctx: str, tick_id: str):
        from agent.soul.heartbeat.bridge import EmotionalSignal

        if picked_id:
            node = self._nodes.get(picked_id)
            if node is not None:
                intensity = node_emotion_intensity(node)
                hint = ""
                for attr in ("reconstructed_fact", "fact", "perception", "content"):
                    val = getattr(node, attr, "")
                    if val:
                        hint = str(val)[:200]
                        break
                return EmotionalSignal(
                    dominant_emotion=node.emotion or emotional_ctx,
                    dominant_valence=node.valence,
                    intensity=round(intensity, 3),
                    source_unit_ids=[picked_id],
                    narrative_hint=hint,
                    tick_id=tick_id,
                )

        if wandered_units:
            top = max(wandered_units, key=lambda s: node_emotion_intensity(s.unit))
            avg_intensity = sum(node_emotion_intensity(s.unit) for s in wandered_units) / len(wandered_units)
            return EmotionalSignal(
                dominant_emotion=top.unit.emotion or emotional_ctx,
                dominant_valence=top.unit.valence,
                intensity=round(avg_intensity, 3),
                source_unit_ids=[s.unit.id for s in wandered_units],
                tick_id=tick_id,
            )

        return EmotionalSignal(tick_id=tick_id)
