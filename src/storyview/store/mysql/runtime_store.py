from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from storyview.types import StatePatch

if TYPE_CHECKING:
    from infra.db.mysql import MySQLClient


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _new_id() -> str:
    return str(uuid.uuid4())


class StoryRuntimeStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def get(self, world_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_runtime WHERE world_id = %s",
                    (world_id,),
                )
                return cur.fetchone()

    def ensure(self, world_id: str, *, world_time: str = "") -> dict:
        row = self.get(world_id)
        if row is not None:
            return row
        now = _utcnow()
        wt = world_time or now.isoformat(timespec="seconds")
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_runtime
                    (world_id, current_location_id, world_time, scene_snapshot_json, active_arc_id, updated_at)
                    VALUES (%s, NULL, %s, %s, NULL, %s)
                    """,
                    (world_id, wt, "{}", now),
                )
        row = self.get(world_id)
        if row is None:
            raise RuntimeError(f"failed to create story runtime {world_id}")
        return row

    def update_snapshot(self, world_id: str, scene_text: str) -> None:
        now = _utcnow()
        snapshot = json.dumps({"scene_text": scene_text}, ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE story_runtime
                    SET scene_snapshot_json = %s, updated_at = %s
                    WHERE world_id = %s
                    """,
                    (snapshot, now, world_id),
                )

    def snapshot_text(self, world_id: str) -> str:
        row = self.get(world_id)
        if row is None:
            return ""
        raw = row.get("scene_snapshot_json")
        if isinstance(raw, str):
            data = json.loads(raw) if raw else {}
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {}
        return str(data.get("scene_text") or "")

    def advance_world_time(self, world_id: str, iso_time: str) -> None:
        now = _utcnow()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE story_runtime
                    SET world_time = %s, updated_at = %s
                    WHERE world_id = %s
                    """,
                    (iso_time, now, world_id),
                )

    def apply_patch(self, world_id: str, patch: StatePatch) -> None:
        now = _utcnow()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                if patch.move_to_location_id:
                    cur.execute(
                        """
                        UPDATE story_runtime
                        SET current_location_id = %s, updated_at = %s
                        WHERE world_id = %s
                        """,
                        (patch.move_to_location_id, now, world_id),
                    )
                for entity_id, delta in patch.entity_deltas.items():
                    cur.execute(
                        "SELECT state_json FROM story_entity WHERE id = %s",
                        (entity_id,),
                    )
                    row = cur.fetchone()
                    if row is None:
                        continue
                    raw = row.get("state_json")
                    if isinstance(raw, str):
                        state = json.loads(raw) if raw else {}
                    elif isinstance(raw, dict):
                        state = dict(raw)
                    else:
                        state = {}
                    for key, value in delta.items():
                        state[key] = value
                    cur.execute(
                        "UPDATE story_entity SET state_json = %s WHERE id = %s",
                        (json.dumps(state, ensure_ascii=False), entity_id),
                    )


class StoryEventStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def create_open(
        self,
        world_id: str,
        *,
        kind: str,
        cue: str,
        scene_text: str = "",
    ) -> str:
        event_id = _new_id()
        now = _utcnow()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_event
                    (event_id, world_id, kind, status, scene_text, cue, created_at)
                    VALUES (%s, %s, %s, 'open', %s, %s, %s)
                    """,
                    (event_id, world_id, kind, scene_text, cue, now),
                )
        return event_id

    def get(self, event_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM story_event WHERE event_id = %s",
                    (event_id,),
                )
                return cur.fetchone()

    def mark_resolved(self, event_id: str, scene_text: str) -> None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE story_event
                    SET status = 'resolved', scene_text = %s
                    WHERE event_id = %s
                    """,
                    (scene_text, event_id),
                )

    def append_log(
        self,
        event_id: str,
        world_id: str,
        *,
        scene_text: str,
        resolution_text: str,
        dice_value: int,
        dice_tendency: str,
        deviation: bool,
        deviation_note: str,
        state_patch: StatePatch,
    ) -> str:
        log_id = _new_id()
        now = _utcnow()
        patch_json = json.dumps(state_patch.to_dict(), ensure_ascii=False)
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_event_log
                    (id, event_id, world_id, scene_text, resolution_text,
                     dice_value, dice_tendency, deviation_flag, deviation_note,
                     state_patch_json, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        log_id,
                        event_id,
                        world_id,
                        scene_text,
                        resolution_text,
                        dice_value,
                        dice_tendency,
                        1 if deviation else 0,
                        deviation_note,
                        patch_json,
                        now,
                    ),
                )
        return log_id


class StoryOutlineStore:
    def __init__(self, mysql_client: MySQLClient) -> None:
        self._db = mysql_client

    def active_arc(self, world_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_outline_arc
                    WHERE world_id = %s AND status = 'active'
                    ORDER BY title
                    LIMIT 1
                    """,
                    (world_id,),
                )
                return cur.fetchone()

    def next_optional_beat(self, arc_id: str) -> dict | None:
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM story_outline_beat
                    WHERE arc_id = %s AND required = 0
                    ORDER BY seq ASC
                    LIMIT 1
                    """,
                    (arc_id,),
                )
                return cur.fetchone()

    def insert_arc(self, world_id: str, title: str, *, arc_id: str | None = None) -> str:
        aid = arc_id or _new_id()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_outline_arc (id, world_id, title, status)
                    VALUES (%s, %s, %s, 'active')
                    ON DUPLICATE KEY UPDATE title = VALUES(title)
                    """,
                    (aid, world_id, title),
                )
        return aid

    def insert_beat(
        self,
        arc_id: str,
        *,
        seq: int,
        summary: str,
        required: bool = False,
        beat_id: str | None = None,
    ) -> str:
        bid = beat_id or _new_id()
        with self._db.conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO story_outline_beat (id, arc_id, seq, summary, required)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE summary = VALUES(summary)
                    """,
                    (bid, arc_id, seq, summary, 1 if required else 0),
                )
        return bid
