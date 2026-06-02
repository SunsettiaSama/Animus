from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from storyview.types import SceneEdge, SceneUnit

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


def _new_id() -> str:
    return str(uuid.uuid4())


def _parse_tags(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        data = json.loads(raw) if raw else []
    elif isinstance(raw, list):
        data = raw
    else:
        return ()
    return tuple(str(item).strip() for item in data if str(item).strip())


def _row_to_scene(row: dict) -> SceneUnit:
    return SceneUnit(
        id=str(row["id"]),
        world_id=str(row["world_id"]),
        name=str(row.get("name") or ""),
        narrative=str(row.get("narrative") or ""),
        location_id=str(row["location_id"]) if row.get("location_id") else None,
        tags=_parse_tags(row.get("tags_json")),
    )


def _row_to_edge(row: dict) -> SceneEdge:
    return SceneEdge(
        id=str(row["id"]),
        world_id=str(row["world_id"]),
        from_scene_id=str(row["from_scene_id"]),
        to_scene_id=str(row["to_scene_id"]),
        transition_text=str(row.get("transition_text") or ""),
        weight=int(row.get("weight") or 10),
    )


class SceneNodeStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def upsert(
        self,
        world_id: str,
        *,
        name: str,
        narrative: str,
        location_id: str | None = None,
        tags: list[str] | None = None,
        scene_id: str | None = None,
        meta: dict | None = None,
    ) -> str:
        sid = scene_id or _new_id()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_scene
                    (id, world_id, name, narrative, location_id, tags_json, meta_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        narrative = VALUES(narrative),
                        location_id = VALUES(location_id),
                        tags_json = VALUES(tags_json),
                        meta_json = VALUES(meta_json)
                    """,
                    (sid, world_id, name, narrative, location_id, tags_json, meta_json),
                )
        return sid

    def get(self, scene_id: str) -> SceneUnit | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_scene WHERE id = %s",
                    (scene_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_scene(row)

    def list_by_world(self, world_id: str) -> list[SceneUnit]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_scene WHERE world_id = %s ORDER BY name",
                    (world_id,),
                )
                rows = cur.fetchall()
        return [_row_to_scene(row) for row in rows]

    def find_by_location(self, world_id: str, location_id: str) -> SceneUnit | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_scene
                    WHERE world_id = %s AND location_id = %s
                    LIMIT 1
                    """,
                    (world_id, location_id),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_scene(row)


class SceneEdgeStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def link(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
        edge_id: str | None = None,
    ) -> str:
        eid = edge_id or _new_id()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_scene_edge
                    (id, world_id, from_scene_id, to_scene_id, transition_text, weight)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        from_scene_id = VALUES(from_scene_id),
                        to_scene_id = VALUES(to_scene_id),
                        transition_text = VALUES(transition_text),
                        weight = VALUES(weight)
                    """,
                    (eid, world_id, from_scene_id, to_scene_id, transition_text, weight),
                )
        return eid

    def get(self, edge_id: str) -> SceneEdge | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_scene_edge WHERE id = %s",
                    (edge_id,),
                )
                row = cur.fetchone()
        if row is None:
            return None
        return _row_to_edge(row)

    def out_edges(self, scene_id: str) -> list[SceneEdge]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_scene_edge
                    WHERE from_scene_id = %s
                    ORDER BY weight DESC
                    """,
                    (scene_id,),
                )
                rows = cur.fetchall()
        return [_row_to_edge(row) for row in rows]

    def in_edges(self, scene_id: str) -> list[SceneEdge]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_scene_edge
                    WHERE to_scene_id = %s
                    ORDER BY weight DESC
                    """,
                    (scene_id,),
                )
                rows = cur.fetchall()
        return [_row_to_edge(row) for row in rows]

    def list_by_world(self, world_id: str) -> list[SceneEdge]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_scene_edge WHERE world_id = %s",
                    (world_id,),
                )
                rows = cur.fetchall()
        return [_row_to_edge(row) for row in rows]


class SceneStore:
    """场景图存储聚合：节点 + 边。"""

    def __init__(self, mysql_client: MySQLClient) -> None:
        self.nodes = SceneNodeStore(mysql_client)
        self.edges = SceneEdgeStore(mysql_client)
