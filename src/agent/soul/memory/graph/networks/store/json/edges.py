from __future__ import annotations

from agent.soul.memory.domain import EdgeType, MemoryEdge
from agent.soul.memory.graph.networks.store.codec import edge_to_row_params, row_to_edge
from infra.storage import JsonStorageService


class JsonEdgeStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("memory/edges")

    def put(self, edge: MemoryEdge) -> None:
        self._rows.upsert(edge.id, edge_to_row_params(edge))

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]:
        def _match(row: dict) -> bool:
            if row.get("from_id") != node_id:
                return False
            return edge_type is None or row.get("edge_type") == edge_type.value

        return [row_to_edge(row) for row in self._rows.filter(_match)]

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]:
        def _match(row: dict) -> bool:
            if row.get("to_id") != node_id:
                return False
            return edge_type is None or row.get("edge_type") == edge_type.value

        return [row_to_edge(row) for row in self._rows.filter(_match)]

    def delete_edge(self, edge_id: str) -> None:
        self._rows.delete(edge_id)

    def delete_by_node(self, node_id: str) -> None:
        for row in self._rows.all():
            if row.get("from_id") == node_id or row.get("to_id") == node_id:
                self._rows.delete(str(row["id"]))
