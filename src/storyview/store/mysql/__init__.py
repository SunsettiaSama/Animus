from __future__ import annotations

from storyview.store.mysql.lore_store import StoryLoreStore
from storyview.store.mysql.runtime_store import (
    StoryEventStore,
    StoryLocationSnapshotStore,
    StoryOutlineStore,
    StoryRuntimeStore,
)
from storyview.store.mysql.scene_store import SceneStore
from storyview.store.mysql.world_store import StorySchemaStore, StoryWorldStore


class StoryStoreBundle:
    def __init__(self, mysql_client) -> None:
        self.schema = StorySchemaStore(mysql_client)
        self.world = StoryWorldStore(mysql_client)
        self.lore = StoryLoreStore(mysql_client)
        self.scene = SceneStore(mysql_client)
        self.runtime = StoryRuntimeStore(mysql_client)
        self.location_snapshots = StoryLocationSnapshotStore(mysql_client)
        self.events = StoryEventStore(mysql_client)
        self.outline = StoryOutlineStore(mysql_client)

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
