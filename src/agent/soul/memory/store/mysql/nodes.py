from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent.soul.memory.domain import GraphNode, MemoryNetwork, SocialNodeRole
from agent.soul.memory.store.codec import node_to_row_params, row_to_node

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

_INSERT_SQL = """
INSERT INTO soul_memory_units (
    id, memory_type, network, interactor_id, node_role,
    focus, emotion, emotion_intensity, valence,
    tier, base_activation, recall_count, rehearsal_count, narrative_ref_count,
    last_accessed, created_at, meta_json,
    fact, perception,
    source_id, reconstructed_fact, trigger_ctx,
    narrative, source_ids_json, chapter,
    core_traits, trait_version, last_evolved_at,
    neighborhood_label, neighborhood_content
) VALUES (
    %(id)s, %(memory_type)s, %(network)s, %(interactor_id)s, %(node_role)s,
    %(focus)s, %(emotion)s, %(emotion_intensity)s, %(valence)s,
    %(tier)s, %(base_activation)s, %(recall_count)s, %(rehearsal_count)s, %(narrative_ref_count)s,
    %(last_accessed)s, %(created_at)s, %(meta_json)s,
    %(fact)s, %(perception)s,
    %(source_id)s, %(reconstructed_fact)s, %(trigger_ctx)s,
    %(narrative)s, %(source_ids_json)s, %(chapter)s,
    %(core_traits)s, %(trait_version)s, %(last_evolved_at)s,
    %(neighborhood_label)s, %(neighborhood_content)s
)
ON DUPLICATE KEY UPDATE
    network = VALUES(network),
    interactor_id = VALUES(interactor_id),
    node_role = VALUES(node_role),
    focus = VALUES(focus),
    emotion = VALUES(emotion),
    emotion_intensity = VALUES(emotion_intensity),
    valence = VALUES(valence),
    tier = VALUES(tier),
    base_activation = VALUES(base_activation),
    recall_count = VALUES(recall_count),
    rehearsal_count = VALUES(rehearsal_count),
    narrative_ref_count = VALUES(narrative_ref_count),
    last_accessed = VALUES(last_accessed),
    meta_json = VALUES(meta_json),
    fact = VALUES(fact),
    perception = VALUES(perception),
    reconstructed_fact = VALUES(reconstructed_fact),
    trigger_ctx = VALUES(trigger_ctx),
    narrative = VALUES(narrative),
    source_ids_json = VALUES(source_ids_json),
    chapter = VALUES(chapter),
    core_traits = VALUES(core_traits),
    trait_version = VALUES(trait_version),
    last_evolved_at = VALUES(last_evolved_at),
    neighborhood_label = VALUES(neighborhood_label),
    neighborhood_content = VALUES(neighborhood_content)
"""


class MySQLNodeStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def init_schema(self) -> None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            sql = f.read()
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)

    def put(self, node: GraphNode) -> None:
        params = node_to_row_params(node)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT_SQL, params)

    def get(self, node_id: str) -> GraphNode | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM soul_memory_units WHERE id=%s AND archived=0",
                    (node_id,),
                )
                row = cur.fetchone()
        return row_to_node(row) if row else None

    def get_many(self, node_ids: list[str]) -> list[GraphNode]:
        if not node_ids:
            return []
        placeholders = ",".join(["%s"] * len(node_ids))
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE id IN ({placeholders}) AND archived=0",
                    node_ids,
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def list_by_network(self, network: MemoryNetwork, *, limit: int = 50) -> list[GraphNode]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM soul_memory_units
                    WHERE archived=0 AND network=%s
                    ORDER BY last_accessed DESC
                    LIMIT %s
                    """,
                    (network.value, limit),
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def list_by_interactor(
        self,
        interactor_id: str,
        role: SocialNodeRole | None = None,
        *,
        limit: int = 50,
    ) -> list[GraphNode]:
        conds = ["archived=0", "interactor_id=%s"]
        params: list = [interactor_id]
        if role is not None:
            conds.append("node_role=%s")
            params.append(role.value)
        params.append(limit)
        where = " AND ".join(conds)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def list_recent(
        self,
        memory_type: str | None = None,
        valence=None,
        network: MemoryNetwork | None = None,
        limit: int = 50,
    ) -> list[GraphNode]:
        conds = ["archived=0"]
        params: list = []
        if memory_type:
            conds.append("memory_type=%s")
            params.append(memory_type)
        if valence is not None:
            conds.append("valence=%s")
            params.append(valence.value)
        if network is not None:
            conds.append("network=%s")
            params.append(network.value)
        where = " AND ".join(conds)
        params.append(limit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def list_all(self, limit: int = 2000, network: MemoryNetwork | None = None) -> list[GraphNode]:
        conds = ["archived=0"]
        params: list = []
        if network is not None:
            conds.append("network=%s")
            params.append(network.value)
        params.append(limit)
        where = " AND ".join(conds)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def query_by_fields(
        self,
        memory_type: str | None = None,
        valence=None,
        chapter: str | None = None,
        source_id: str | None = None,
        emotion_contains: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int = 50,
        network: MemoryNetwork | None = None,
    ) -> list[GraphNode]:
        conds = ["archived=0"]
        params: list = []
        if memory_type:
            conds.append("memory_type=%s")
            params.append(memory_type)
        if valence is not None:
            conds.append("valence=%s")
            params.append(valence.value)
        if chapter:
            conds.append("chapter=%s")
            params.append(chapter)
        if source_id:
            conds.append("source_id=%s")
            params.append(source_id)
        if emotion_contains:
            conds.append("emotion LIKE %s")
            params.append(f"%{emotion_contains}%")
        if created_after:
            conds.append("created_at >= %s")
            params.append(created_after)
        if created_before:
            conds.append("created_at <= %s")
            params.append(created_before)
        if network is not None:
            conds.append("network=%s")
            params.append(network.value)
        where = " AND ".join(conds)
        params.append(limit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM soul_memory_units WHERE {where} ORDER BY last_accessed DESC LIMIT %s",
                    params,
                )
                rows = cur.fetchall()
        return [row_to_node(r) for r in rows]

    def get_by_life_event_id(self, life_event_id: str) -> GraphNode | None:
        if not life_event_id:
            return None
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM soul_memory_units
                    WHERE archived=0
                      AND memory_type='factual'
                      AND JSON_UNQUOTE(JSON_EXTRACT(meta_json, '$.life_event_id'))=%s
                    LIMIT 1
                    """,
                    (life_event_id,),
                )
                row = cur.fetchone()
        return row_to_node(row) if row else None

    def get_core_for_interactor(self, interactor_id: str) -> GraphNode | None:
        nodes = self.list_by_interactor(
            interactor_id,
            SocialNodeRole.core,
            limit=1,
        )
        return nodes[0] if nodes else None

    def on_recall(self, node_id: str) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET recall_count=recall_count+1, last_accessed=%s WHERE id=%s",
                    (now, node_id),
                )

    def add_rehearsal(self, node_id: str) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET rehearsal_count=rehearsal_count+1, last_accessed=%s WHERE id=%s",
                    (now, node_id),
                )

    def add_narrative_ref(self, node_id: str) -> None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET narrative_ref_count=narrative_ref_count+1 WHERE id=%s",
                    (node_id,),
                )

    def archive(self, node_id: str) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE soul_memory_units SET archived=1, archived_at=%s WHERE id=%s",
                    (now, node_id),
                )

    def forget_scan(
        self,
        *,
        threshold: float = 0.05,
        half_life_days: float = 30.0,
        dry_run: bool = False,
        network: MemoryNetwork | None = None,
    ) -> list[str]:
        conds = ["archived=0"]
        params: list = []
        if network is not None:
            conds.append("network=%s")
            params.append(network.value)
        where = " AND ".join(conds)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, base_activation, recall_count, last_accessed
                    FROM soul_memory_units WHERE {where}
                    """,
                    params,
                )
                rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        to_archive: list[str] = []
        for row in rows:
            last = row["last_accessed"]
            if isinstance(last, str):
                last = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            elif last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            delta = (now - last).total_seconds() / 86400.0
            decay = math.exp(-math.log(2) / half_life_days * max(delta, 0.0))
            boost = math.log1p(int(row["recall_count"] or 0))
            activation = min(1.0, float(row["base_activation"] or 0.5) * decay + boost)
            if activation < threshold:
                to_archive.append(row["id"])

        if not dry_run:
            for uid in to_archive:
                self.archive(uid)
        return to_archive
