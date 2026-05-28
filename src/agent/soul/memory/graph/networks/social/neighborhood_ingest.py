from __future__ import annotations

from agent.soul.memory.domain import SocialCoreNode, SocialNeighborhoodNode, SocialNodeRole
from agent.soul.memory.graph.traversal import GraphTraversal
from agent.soul.memory.ports import GraphNodeStore
from agent.soul.memory.processors.neighborhood_extractor import NeighborhoodCandidate, NeighborhoodExtractorPort


class NeighborhoodIngestor:
    def __init__(
        self,
        nodes: GraphNodeStore,
        traversal: GraphTraversal,
        extractor: NeighborhoodExtractorPort,
    ) -> None:
        self._nodes = nodes
        self._traversal = traversal
        self._extractor = extractor

    def ingest(
        self,
        core: SocialCoreNode,
        candidates: list[NeighborhoodCandidate],
    ) -> list[SocialNeighborhoodNode]:
        if not candidates:
            return []
        existing = self._nodes.list_by_interactor(
            core.interactor_id,
            SocialNodeRole.neighborhood,
            limit=200,
        )
        label_index: dict[str, SocialNeighborhoodNode] = {}
        for node in existing:
            if isinstance(node, SocialNeighborhoodNode):
                label_index[node.label.strip().lower()] = node

        created: list[SocialNeighborhoodNode] = []
        for candidate in candidates:
            label_key = candidate.label.strip().lower()
            node = label_index.get(label_key)
            if node is None:
                node = SocialNeighborhoodNode(
                    interactor_id=core.interactor_id,
                    focus=candidate.label[:60] or candidate.content[:60],
                    label=candidate.label,
                    content=candidate.content,
                )
                self._nodes.put(node)
                label_index[label_key] = node
                self._traversal.link_about(core.id, node.id)
                created.append(node)
            elif candidate.content.strip() and candidate.content not in node.content:
                node.content = f"{node.content}\n{candidate.content}".strip()
                node.focus = node.label[:60] or node.content[:60]
                self._nodes.put(node)

            for related in candidate.related_labels:
                rel_key = related.strip().lower()
                if not rel_key:
                    continue
                related_node = label_index.get(rel_key)
                if related_node is None:
                    related_node = SocialNeighborhoodNode(
                        interactor_id=core.interactor_id,
                        focus=related[:60],
                        label=related,
                        content=related,
                    )
                    self._nodes.put(related_node)
                    label_index[rel_key] = related_node
                    self._traversal.link_about(core.id, related_node.id)
                    created.append(related_node)
                if related_node.id != node.id:
                    self._traversal.link_related_to(node.id, related_node.id)

        return created
