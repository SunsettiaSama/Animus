from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.memory.domain import EdgeType, MemoryEdge
from agent.soul.memory.graph.networks.store.codec import edge_to_row_params, row_to_edge

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient

_INSERT_SQL = """
INSERT INTO soul_memory_edges (id, from_id, to_id, edge_type, weight, meta_json, created_at)
VALUES (%(id)s, %(from_id)s, %(to_id)s, %(edge_type)s, %(weight)s, %(meta_json)s, %(created_at)s)
ON DUPLICATE KEY UPDATE
    weight = VALUES(weight),
    meta_json = VALUES(meta_json)
"""


class MySQLEdgeStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def put(self, edge: MemoryEdge) -> None:
        params = edge_to_row_params(edge)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_SQL, params)

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]:
        conds = ["from_id=%s"]
        params: list = [node_id]
        if edge_type is not None:
            conds.append("edge_type=%s")
            params.append(edge_type.value)
        where = " AND ".join(conds)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM soul_memory_edges WHERE {where}", params)
                rows = cur.fetchall()
        return [row_to_edge(r) for r in rows]

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None) -> list[MemoryEdge]:
        conds = ["to_id=%s"]
        params: list = [node_id]
        if edge_type is not None:
            conds.append("edge_type=%s")
            params.append(edge_type.value)
        where = " AND ".join(conds)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM soul_memory_edges WHERE {where}", params)
                rows = cur.fetchall()
        return [row_to_edge(r) for r in rows]

    def delete_edge(self, edge_id: str) -> None:
        if not edge_id:
            return
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM soul_memory_edges WHERE id=%s", (edge_id,))

    def delete_by_node(self, node_id: str) -> None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM soul_memory_edges WHERE from_id=%s OR to_id=%s",
                    (node_id, node_id),
                )
