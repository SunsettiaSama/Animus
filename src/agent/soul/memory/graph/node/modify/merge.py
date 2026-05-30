from __future__ import annotations

from agent.soul.memory.domain.enums import SocialNodeRole
from agent.soul.memory.graph.networks.social.node import SocialCoreNode, SocialNeighborhoodNode
from agent.soul.memory.graph.node.create.persist import NodePersister
from agent.soul.memory.graph.node_store import GraphNodeStore
from agent.soul.memory.graph.traversal import GraphTraversal


def merge_neighborhood(
    *,
    nodes: GraphNodeStore,
    traversal: GraphTraversal,
    persister: NodePersister,
    core: SocialCoreNode,
    node: SocialNeighborhoodNode,
) -> SocialNeighborhoodNode:
    """按 label 合并 neighborhood；不存在则创建并 link about core。"""
    label_key = node.label.strip().lower()
    existing_nodes = nodes.list_by_interactor(
        core.interactor_id,
        SocialNodeRole.neighborhood,
        limit=200,
    )
    for existing in existing_nodes:
        if not isinstance(existing, SocialNeighborhoodNode):
            continue
        if existing.label.strip().lower() != label_key:
            continue
        if node.content.strip() and node.content not in existing.content:
            existing.content = f"{existing.content}\n{node.content}".strip()
            existing.focus = existing.label[:60] or existing.content[:60]
        if node.related_interactor_ids:
            merged_ids = list(
                dict.fromkeys(
                    [*existing.related_interactor_ids, *node.related_interactor_ids]
                )
            )
            existing.related_interactor_ids = merged_ids
        existing.meta = {**existing.meta, **node.meta}
        persister.write(existing)
        traversal.link_about(core.id, existing.id)
        return existing

    persister.write(node)
    traversal.link_about(core.id, node.id)
    return node
