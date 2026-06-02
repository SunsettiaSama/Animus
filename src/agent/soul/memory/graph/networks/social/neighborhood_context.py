from __future__ import annotations

from datetime import datetime, timezone

from agent.soul.memory.graph.networks.social.node import SocialCoreNode, SocialNeighborhoodNode
from agent.soul.memory.graph.networks.social.time_weight import event_time_weight

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork


def gather_weighted_neighborhood_context(
    social: SocialMemoryNetwork,
    interactor_id: str,
    *,
    query: str = "",
    top_k: int = 4,
    event_time_half_life_days: float = 60.0,
) -> tuple[tuple[str, float], ...]:
    """拉取交互者邻近 social 节点，按检索分 × 时间权重排序。"""
    iid = interactor_id.strip()
    if not iid:
        return ()
    core = social._nodes.get_core_for_interactor(iid)
    if not isinstance(core, SocialCoreNode):
        return ()

    q = query.strip() or core.portrait.name.strip() or iid
    scored = social._query.recall(
        q,
        top_k=max(top_k * 4, 8),
        interactor_id=iid,
    )
    now = datetime.now(timezone.utc)
    ranked: list[tuple[str, float]] = []
    seen: set[str] = set()

    for item in scored:
        unit = item.unit
        if not isinstance(unit, SocialNeighborhoodNode):
            continue
        if unit.id in seen:
            continue
        text = unit.content.strip() or unit.label.strip()
        if not text:
            continue
        seen.add(unit.id)
        tw = event_time_weight(unit, now, half_life_days=event_time_half_life_days)
        ranked.append((text, float(item.final_score) * tw))

    start_scores = {core.id: 1.0}
    hits = social._traversal.bfs(
        start_scores,
        max_hops=2,
        hop_decay=0.82,
        threshold=0.08,
    )
    for hit in hits:
        if hit.node_id in seen:
            continue
        node = social._nodes.get(hit.node_id)
        if not isinstance(node, SocialNeighborhoodNode):
            continue
        if node.interactor_id and node.interactor_id != iid:
            continue
        text = node.content.strip() or node.label.strip()
        if not text:
            continue
        seen.add(node.id)
        tw = event_time_weight(node, now, half_life_days=event_time_half_life_days)
        ranked.append((text, float(hit.score) * tw))

    ranked.sort(key=lambda row: row[1], reverse=True)
    return tuple(ranked[:top_k])
