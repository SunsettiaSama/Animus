from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_id() -> str:
    return str(uuid.uuid4())


class StoryLoreStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def insert_lore(
        self,
        world_id: str,
        *,
        category: str,
        title: str,
        body: str,
        tags: list[str] | None = None,
        weight: int = 10,
        lore_id: str | None = None,
        links: list[tuple[str, str]] | None = None,
    ) -> str:
        lid = lore_id or _new_id()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_lore
                    (id, world_id, category, title, body, tags_json, weight)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        category = VALUES(category),
                        title = VALUES(title),
                        body = VALUES(body),
                        tags_json = VALUES(tags_json),
                        weight = VALUES(weight)
                    """,
                    (lid, world_id, category, title, body, tags_json, weight),
                )
                for ref_type, ref_id in links or []:
                    cur.execute(
                        """
                        INSERT INTO story_lore_link (id, lore_id, ref_type, ref_id)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE ref_type = VALUES(ref_type)
                        """,
                        (_new_id(), lid, ref_type, ref_id),
                    )
        return lid

    def insert_location(
        self,
        world_id: str,
        *,
        name: str,
        description: str = "",
        atmosphere: str = "",
        parent_id: str | None = None,
        tags: list[str] | None = None,
        location_id: str | None = None,
    ) -> str:
        loc_id = location_id or _new_id()
        tags_json = json.dumps(tags or [], ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_location
                    (id, world_id, parent_id, name, description, atmosphere, tags_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        description = VALUES(description),
                        atmosphere = VALUES(atmosphere),
                        tags_json = VALUES(tags_json)
                    """,
                    (loc_id, world_id, parent_id, name, description, atmosphere, tags_json),
                )
        return loc_id

    def insert_entity(
        self,
        world_id: str,
        *,
        name: str,
        kind: str = "object",
        description: str = "",
        location_id: str | None = None,
        state: dict | None = None,
        entity_id: str | None = None,
    ) -> str:
        ent_id = entity_id or _new_id()
        state_json = json.dumps(state or {}, ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_entity
                    (id, world_id, location_id, name, kind, description, state_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        name = VALUES(name),
                        kind = VALUES(kind),
                        description = VALUES(description),
                        location_id = VALUES(location_id),
                        state_json = VALUES(state_json)
                    """,
                    (ent_id, world_id, location_id, name, kind, description, state_json),
                )
        return ent_id

    def list_locations(self, world_id: str) -> list[dict]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_location WHERE world_id = %s",
                    (world_id,),
                )
                return list(cur.fetchall())

    def get_location(self, location_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_location WHERE id = %s",
                    (location_id,),
                )
                return cur.fetchone()

    def location_ancestors(self, location_id: str) -> list[str]:
        ids: list[str] = []
        current = location_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            ids.append(current)
            row = self.get_location(current)
            if row is None:
                break
            current = row.get("parent_id")
        return ids

    def entities_at_location(self, world_id: str, location_id: str) -> list[dict]:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_entity
                    WHERE world_id = %s AND location_id = %s
                    """,
                    (world_id, location_id),
                )
                return list(cur.fetchall())

    def get_entity(self, entity_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_entity WHERE id = %s",
                    (entity_id,),
                )
                return cur.fetchone()

    def search_by_cue(self, world_id: str, cue: str, *, limit: int = 12) -> list[dict]:
        tokens = [t.strip() for t in cue.replace("，", " ").replace(",", " ").split() if t.strip()]
        if not tokens:
            with self._db.conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT * FROM story_lore
                        WHERE world_id = %s
                        ORDER BY weight DESC
                        LIMIT %s
                        """,
                        (world_id, limit),
                    )
                    return list(cur.fetchall())
        like_clauses = " OR ".join(["body LIKE %s OR title LIKE %s"] * len(tokens))
        params: list[Any] = [world_id]
        for token in tokens:
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        params.append(limit)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT * FROM story_lore
                    WHERE world_id = %s AND ({like_clauses})
                    ORDER BY weight DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return list(cur.fetchall())

    def lore_for_refs(self, ref_ids: list[str], *, limit: int = 12) -> list[dict]:
        if not ref_ids:
            return []
        placeholders = ",".join(["%s"] * len(ref_ids))
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT l.* FROM story_lore l
                    INNER JOIN story_lore_link k ON k.lore_id = l.id
                    WHERE k.ref_id IN ({placeholders})
                    ORDER BY l.weight DESC
                    LIMIT %s
                    """,
                    (*ref_ids, limit),
                )
                return list(cur.fetchall())

    def retrieve_for_cue(
        self,
        world_id: str,
        cue: str,
        *,
        current_location_id: str | None = None,
        limit: int = 8,
    ) -> tuple[list[dict], list[dict], list[str]]:
        ref_ids: list[str] = []
        entities: list[dict] = []
        if current_location_id:
            ref_ids.extend(self.location_ancestors(current_location_id))
            entities = self.entities_at_location(world_id, current_location_id)
            ref_ids.extend(e["id"] for e in entities)

        linked = self.lore_for_refs(ref_ids, limit=limit) if ref_ids else []
        keyword = self.search_by_cue(world_id, cue, limit=limit)
        seen: set[str] = set()
        lore_rows: list[dict] = []
        for row in linked + keyword:
            lid = row["id"]
            if lid in seen:
                continue
            seen.add(lid)
            lore_rows.append(row)
            if len(lore_rows) >= limit:
                break
        lore_ids = [r["id"] for r in lore_rows]
        return lore_rows, entities, lore_ids

    def update_entity_state(self, entity_id: str, state: dict) -> None:
        state_json = json.dumps(state, ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE story_entity SET state_json = %s WHERE id = %s",
                    (state_json, entity_id),
                )
