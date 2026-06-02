from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_id() -> str:
    return str(uuid.uuid4())


class StorySchemaStore:
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


class StoryWorldStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def get(self, world_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_world WHERE world_id = %s",
                    (world_id,),
                )
                return cur.fetchone()

    def ensure(self, world_id: str, *, title: str = "", era: str = "", setting: str = "",
               tone: str = "", canon_json: dict | None = None) -> dict:
        row = self.get(world_id)
        if row is not None:
            return row
        now = _utcnow()
        canon = json.dumps(canon_json or {}, ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_world
                    (world_id, title, era, setting, tone, canon_json, meta_json, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (world_id, title, era, setting, tone, canon, "{}", now, now),
                )
        row = self.get(world_id)
        if row is None:
            raise RuntimeError(f"failed to create story world {world_id}")
        return row

    def canon_rules(self, world_id: str) -> dict[str, list[str]]:
        row = self.get(world_id)
        if row is None:
            return {"forbidden": [], "must": [], "prefer": []}
        raw = row.get("canon_json")
        if isinstance(raw, str):
            data = json.loads(raw) if raw else {}
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {}
        return {
            "forbidden": list(data.get("forbidden") or []),
            "must": list(data.get("must") or []),
            "prefer": list(data.get("prefer") or data.get("canon") or []),
        }
