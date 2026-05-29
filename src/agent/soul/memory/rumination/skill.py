from __future__ import annotations

from agent.soul.memory.emergence.spread import SpreadActivationService
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.rumination.types import (
    RuminationConfig,
    RuminationSkillContext,
    RuminationSkillResult,
)
from agent.soul.memory.rumination.writer import RuminationWriter


class RuminationSkill:
    """反刍编排：buffer node → emergence 扩散 → LLM 覆盖改写 + 关系边改写。"""

    def __init__(
        self,
        nodes: GraphNodeStore,
        spread: SpreadActivationService,
        writer: RuminationWriter,
        traversal: GraphTraversal,
        *,
        cfg: RuminationConfig | None = None,
    ) -> None:
        self._nodes = nodes
        self._spread = spread
        self._writer = writer
        self._traversal = traversal
        self._cfg = cfg or RuminationConfig()

    def run(self, ctx: RuminationSkillContext) -> RuminationSkillResult:
        node = self._nodes.get(ctx.node_id)
        if node is None:
            return RuminationSkillResult(
                node_id=ctx.node_id,
                ran=False,
                detail={"reason": "missing_node"},
            )
        if node.MEMORY_TYPE not in ("factual", "reconstructive"):
            return RuminationSkillResult(
                node_id=ctx.node_id,
                ran=False,
                detail={"reason": "unsupported_type", "memory_type": node.MEMORY_TYPE},
            )

        neighbors = self._spread.rumination_neighbors(
            ctx.node_id,
            max_hops=self._cfg.diffusion_max_hops,
            top_k=self._cfg.diffusion_top_k,
            threshold=self._cfg.diffusion_threshold,
        )
        diffusion_ids = [n.unit.id for n in neighbors]

        updated, edge_specs = self._writer.run_skill(
            node,
            neighbors=neighbors,
            persona_profile=ctx.persona_profile,
            trigger=ctx.trigger,
            emotional_context=ctx.emotional_context,
            tick_id=ctx.tick_id,
        )
        applied_edges = self._writer.apply_edges(updated.id, edge_specs, self._traversal)

        return RuminationSkillResult(
            node_id=updated.id,
            ran=True,
            overwritten=True,
            reconstructive_id=updated.id,
            diffusion_ids=diffusion_ids,
            new_edges=applied_edges,
            detail={
                "memory_type": updated.MEMORY_TYPE,
                "focus": updated.focus,
                "emotion": updated.emotion,
                "diffusion_count": len(diffusion_ids),
                "edge_count": len(applied_edges),
            },
        )
