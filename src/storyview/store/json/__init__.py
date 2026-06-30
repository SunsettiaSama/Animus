from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from infra.storage import JsonStorageService
from storyview.types import AgentLocationSnapshot, SceneEdge, SceneUnit, StatePatch


def _utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _new_id() -> str:
    return str(uuid.uuid4())


def _parse_json(raw: Any, default):
    if isinstance(raw, str):
        return json.loads(raw) if raw else default
    if isinstance(raw, dict | list):
        return raw
    return default


def _row_to_scene(row: dict) -> SceneUnit:
    tags = _parse_json(row.get("tags_json"), [])
    meta = _parse_json(row.get("meta_json"), {})
    if not isinstance(meta, dict):
        meta = {}
    return SceneUnit(
        id=str(row["id"]),
        world_id=str(row["world_id"]),
        name=str(row.get("name") or ""),
        narrative=str(row.get("narrative") or ""),
        location_id=str(row["location_id"]) if row.get("location_id") else None,
        tags=tuple(str(item).strip() for item in tags if str(item).strip()),
        meta=dict(meta),
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


class StorySchemaStore:
    def init_schema(self) -> None:
        return None


class StoryWorldStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("story/worlds")

    def get(self, world_id: str) -> dict | None:
        return self._rows.get(world_id)

    def ensure(
        self,
        world_id: str,
        *,
        title: str = "",
        era: str = "",
        setting: str = "",
        tone: str = "",
        canon_json: dict | None = None,
    ) -> dict:
        row = self.get(world_id)
        if row is not None:
            return row
        now = _utc_str()
        row = {
            "world_id": world_id,
            "title": title,
            "era": era,
            "setting": setting,
            "tone": tone,
            "canon_json": json.dumps(canon_json or {}, ensure_ascii=False),
            "meta_json": "{}",
            "created_at": now,
            "updated_at": now,
        }
        self._rows.upsert(world_id, row)
        return row

    def canon_rules(self, world_id: str) -> dict[str, list[str]]:
        row = self.get(world_id)
        if row is None:
            return {"forbidden": [], "must": [], "prefer": []}
        data = _parse_json(row.get("canon_json"), {})
        return {
            "forbidden": list(data.get("forbidden") or []),
            "must": list(data.get("must") or []),
            "prefer": list(data.get("prefer") or data.get("canon") or []),
        }


class StoryLoreStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._lore = storage.collection("story/lore")
        self._links = storage.collection("story/lore_links")
        self._locations = storage.collection("story/locations")
        self._entities = storage.collection("story/entities")

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
        self._lore.upsert(
            lid,
            {
                "id": lid,
                "world_id": world_id,
                "category": category,
                "title": title,
                "body": body,
                "tags_json": json.dumps(tags or [], ensure_ascii=False),
                "weight": weight,
            },
        )
        for ref_type, ref_id in links or []:
            link_id = _new_id()
            self._links.upsert(
                link_id,
                {"id": link_id, "lore_id": lid, "ref_type": ref_type, "ref_id": ref_id},
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
        self._locations.upsert(
            loc_id,
            {
                "id": loc_id,
                "world_id": world_id,
                "parent_id": parent_id,
                "name": name,
                "description": description,
                "atmosphere": atmosphere,
                "tags_json": json.dumps(tags or [], ensure_ascii=False),
            },
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
        self._entities.upsert(
            ent_id,
            {
                "id": ent_id,
                "world_id": world_id,
                "location_id": location_id,
                "name": name,
                "kind": kind,
                "description": description,
                "state_json": json.dumps(state or {}, ensure_ascii=False),
            },
        )
        return ent_id

    def list_locations(self, world_id: str) -> list[dict]:
        return self._locations.filter(lambda row: row.get("world_id") == world_id)

    def get_location(self, location_id: str) -> dict | None:
        return self._locations.get(location_id)

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
            current = str(row.get("parent_id") or "")
        return ids

    def entities_at_location(self, world_id: str, location_id: str) -> list[dict]:
        return self._entities.filter(
            lambda row: row.get("world_id") == world_id and row.get("location_id") == location_id
        )

    def get_entity(self, entity_id: str) -> dict | None:
        return self._entities.get(entity_id)

    def search_by_cue(self, world_id: str, cue: str, *, limit: int = 12) -> list[dict]:
        tokens = [t.strip() for t in cue.replace("，", " ").replace(",", " ").split() if t.strip()]
        rows = self._lore.filter(lambda row: row.get("world_id") == world_id)
        if tokens:
            rows = [
                row for row in rows
                if any(token in str(row.get("body") or "") or token in str(row.get("title") or "") for token in tokens)
            ]
        rows.sort(key=lambda row: int(row.get("weight") or 0), reverse=True)
        return rows[:limit]

    def lore_for_refs(self, ref_ids: list[str], *, limit: int = 12) -> list[dict]:
        if not ref_ids:
            return []
        wanted = set(ref_ids)
        links = self._links.filter(lambda row: row.get("ref_id") in wanted)
        lore_ids = {str(row["lore_id"]) for row in links}
        rows = [row for row in self._lore.all() if row.get("id") in lore_ids]
        rows.sort(key=lambda row: int(row.get("weight") or 0), reverse=True)
        return rows[:limit]

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
            ref_ids.extend(str(e["id"]) for e in entities)
        linked = self.lore_for_refs(ref_ids, limit=limit) if ref_ids else []
        keyword = self.search_by_cue(world_id, cue, limit=limit)
        seen: set[str] = set()
        lore_rows: list[dict] = []
        for row in linked + keyword:
            lid = str(row["id"])
            if lid in seen:
                continue
            seen.add(lid)
            lore_rows.append(row)
            if len(lore_rows) >= limit:
                break
        return lore_rows, entities, [str(row["id"]) for row in lore_rows]

    def update_entity_state(self, entity_id: str, state: dict) -> None:
        row = self._entities.get(entity_id)
        if row is None:
            return
        row["state_json"] = json.dumps(state, ensure_ascii=False)
        self._entities.upsert(entity_id, row)


class SceneNodeStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("story/scenes")

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
        self._rows.upsert(
            sid,
            {
                "id": sid,
                "world_id": world_id,
                "name": name,
                "narrative": narrative,
                "location_id": location_id,
                "tags_json": json.dumps(tags or [], ensure_ascii=False),
                "meta_json": json.dumps(meta or {}, ensure_ascii=False),
            },
        )
        return sid

    def get(self, scene_id: str) -> SceneUnit | None:
        row = self._rows.get(scene_id)
        return _row_to_scene(row) if row else None

    def list_by_world(self, world_id: str) -> list[SceneUnit]:
        rows = self._rows.filter(lambda row: row.get("world_id") == world_id)
        rows.sort(key=lambda row: str(row.get("name") or ""))
        return [_row_to_scene(row) for row in rows]

    def find_by_location(self, world_id: str, location_id: str) -> SceneUnit | None:
        rows = self._rows.filter(
            lambda row: row.get("world_id") == world_id and row.get("location_id") == location_id
        )
        return _row_to_scene(rows[0]) if rows else None


class SceneEdgeStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("story/scene_edges")

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
        self._rows.upsert(
            eid,
            {
                "id": eid,
                "world_id": world_id,
                "from_scene_id": from_scene_id,
                "to_scene_id": to_scene_id,
                "transition_text": transition_text,
                "weight": weight,
            },
        )
        return eid

    def get(self, edge_id: str) -> SceneEdge | None:
        row = self._rows.get(edge_id)
        return _row_to_edge(row) if row else None

    def out_edges(self, scene_id: str) -> list[SceneEdge]:
        rows = self._rows.filter(lambda row: row.get("from_scene_id") == scene_id)
        rows.sort(key=lambda row: int(row.get("weight") or 0), reverse=True)
        return [_row_to_edge(row) for row in rows]

    def in_edges(self, scene_id: str) -> list[SceneEdge]:
        rows = self._rows.filter(lambda row: row.get("to_scene_id") == scene_id)
        rows.sort(key=lambda row: int(row.get("weight") or 0), reverse=True)
        return [_row_to_edge(row) for row in rows]

    def list_by_world(self, world_id: str) -> list[SceneEdge]:
        return [_row_to_edge(row) for row in self._rows.filter(lambda row: row.get("world_id") == world_id)]


class SceneStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self.nodes = SceneNodeStore(storage)
        self.edges = SceneEdgeStore(storage)


class StoryRuntimeStore:
    def __init__(self, storage: JsonStorageService, lore: StoryLoreStore) -> None:
        self._rows = storage.collection("story/runtime")
        self._lore = lore

    def get(self, world_id: str) -> dict | None:
        return self._rows.get(world_id)

    def ensure(self, world_id: str, *, world_time: str = "") -> dict:
        row = self.get(world_id)
        if row is not None:
            return row
        now = _utc_str()
        row = {
            "world_id": world_id,
            "current_location_id": None,
            "world_time": world_time or now,
            "scene_snapshot_json": "{}",
            "active_arc_id": None,
            "updated_at": now,
        }
        self._rows.upsert(world_id, row)
        return row

    def update_snapshot(self, world_id: str, scene_text: str) -> None:
        row = self.ensure(world_id)
        row["scene_snapshot_json"] = json.dumps({"scene_text": scene_text}, ensure_ascii=False)
        row["updated_at"] = _utc_str()
        self._rows.upsert(world_id, row)

    def snapshot_text(self, world_id: str) -> str:
        row = self.get(world_id)
        if row is None:
            return ""
        data = _parse_json(row.get("scene_snapshot_json"), {})
        return str(data.get("scene_text") or "")

    def advance_world_time(self, world_id: str, iso_time: str) -> None:
        row = self.ensure(world_id)
        row["world_time"] = iso_time
        row["updated_at"] = _utc_str()
        self._rows.upsert(world_id, row)

    def apply_patch(self, world_id: str, patch: StatePatch) -> None:
        row = self.ensure(world_id)
        if patch.move_to_location_id:
            row["current_location_id"] = patch.move_to_location_id
            row["updated_at"] = _utc_str()
            self._rows.upsert(world_id, row)
        for entity_id, delta in patch.entity_deltas.items():
            entity = self._lore.get_entity(entity_id)
            if entity is None:
                continue
            state = _parse_json(entity.get("state_json"), {})
            state.update(delta)
            self._lore.update_entity_state(entity_id, state)


class StoryLocationSnapshotStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._rows = storage.collection("story/location_snapshots")

    def append(self, snapshot: AgentLocationSnapshot) -> str:
        row = snapshot.to_dict()
        if not row.get("created_at"):
            row["created_at"] = _utc_str()
        self._rows.upsert(snapshot.snapshot_id, row)
        return snapshot.snapshot_id

    def last(self, world_id: str) -> AgentLocationSnapshot | None:
        rows = self._rows.filter(lambda row: row.get("world_id") == world_id)
        if not rows:
            return None
        rows.sort(
            key=lambda row: (str(row.get("created_at") or ""), str(row.get("snapshot_id") or "")),
            reverse=True,
        )
        return AgentLocationSnapshot.from_dict(rows[0])

    def list_recent(self, world_id: str, *, limit: int = 10) -> list[AgentLocationSnapshot]:
        rows = self._rows.filter(lambda row: row.get("world_id") == world_id)
        rows.sort(
            key=lambda row: (str(row.get("created_at") or ""), str(row.get("snapshot_id") or "")),
            reverse=True,
        )
        return [AgentLocationSnapshot.from_dict(row) for row in rows[: int(limit)]]


class StoryEventStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._events = storage.collection("story/events")
        self._logs = storage.collection("story/event_logs")

    def create_open(self, world_id: str, *, kind: str, cue: str, scene_text: str = "") -> str:
        event_id = _new_id()
        self._events.upsert(
            event_id,
            {
                "event_id": event_id,
                "world_id": world_id,
                "kind": kind,
                "status": "open",
                "scene_text": scene_text,
                "cue": cue,
                "created_at": _utc_str(),
            },
        )
        return event_id

    def get(self, event_id: str) -> dict | None:
        return self._events.get(event_id)

    def mark_resolved(self, event_id: str, scene_text: str) -> None:
        row = self._events.get(event_id)
        if row is None:
            return
        row["status"] = "resolved"
        row["scene_text"] = scene_text
        self._events.upsert(event_id, row)

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
        self._logs.upsert(
            log_id,
            {
                "id": log_id,
                "event_id": event_id,
                "world_id": world_id,
                "scene_text": scene_text,
                "resolution_text": resolution_text,
                "dice_value": dice_value,
                "dice_tendency": dice_tendency,
                "deviation_flag": 1 if deviation else 0,
                "deviation_note": deviation_note,
                "state_patch_json": json.dumps(state_patch.to_dict(), ensure_ascii=False),
                "created_at": _utc_str(),
            },
        )
        return log_id


class StoryOutlineStore:
    def __init__(self, storage: JsonStorageService) -> None:
        self._arcs = storage.collection("story/outline_arcs")
        self._beats = storage.collection("story/outline_beats")

    def active_arc(self, world_id: str) -> dict | None:
        rows = self._arcs.filter(lambda row: row.get("world_id") == world_id and row.get("status") == "active")
        rows.sort(key=lambda row: str(row.get("title") or ""))
        return rows[0] if rows else None

    def next_optional_beat(self, arc_id: str) -> dict | None:
        rows = self._beats.filter(lambda row: row.get("arc_id") == arc_id and not int(row.get("required") or 0))
        rows.sort(key=lambda row: int(row.get("seq") or 0))
        return rows[0] if rows else None

    def insert_arc(self, world_id: str, title: str, *, arc_id: str | None = None) -> str:
        aid = arc_id or _new_id()
        self._arcs.upsert(aid, {"id": aid, "world_id": world_id, "title": title, "status": "active"})
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
        self._beats.upsert(
            bid,
            {"id": bid, "arc_id": arc_id, "seq": seq, "summary": summary, "required": 1 if required else 0},
        )
        return bid


class StoryStoreBundle:
    def __init__(self, storage: JsonStorageService | str) -> None:
        service = storage if isinstance(storage, JsonStorageService) else JsonStorageService(storage)
        self.schema = StorySchemaStore()
        self.world = StoryWorldStore(service)
        self.lore = StoryLoreStore(service)
        self.scene = SceneStore(service)
        self.runtime = StoryRuntimeStore(service, self.lore)
        self.location_snapshots = StoryLocationSnapshotStore(service)
        self.events = StoryEventStore(service)
        self.outline = StoryOutlineStore(service)

    def init_schema(self) -> None:
        self.schema.init_schema()

    def resolve_current_scene_id(self, world_id: str) -> str | None:
        runtime = self.runtime.get(world_id)
        if runtime is None:
            return None
        location_id = runtime.get("current_location_id")
        if not location_id:
            return None
        scene = self.scene.nodes.find_by_location(world_id, str(location_id))
        if scene is None:
            return None
        return scene.id
