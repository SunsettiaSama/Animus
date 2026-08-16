from __future__ import annotations

from dataclasses import dataclass


@dataclass
class _Runtime:
    _snap: str = ""
    _loc: str = "loc-room"

    def ensure(self, world_id: str):
        return {"current_location_id": self._loc, "world_time": ""}

    def snapshot_text(self, world_id: str) -> str:
        return self._snap

    def update_snapshot(self, world_id: str, text: str) -> None:
        self._snap = text


@dataclass
class _World:
    def ensure(self, world_id: str) -> None:
        return None

    def get(self, world_id: str):
        return {"title": "测试世界", "setting": "", "era": "", "tone": ""}

    def canon_rules(self, world_id: str):
        return {"prefer": []}


@dataclass
class _Lore:
    def retrieve_for_cue(self, world_id, cue, *, current_location_id=None):
        return [], [], []

    def get_location(self, loc_id):
        return {"name": "小酒馆"}


@dataclass
class _Events:
    def create_open(self, world_id, *, kind, cue, scene_text):
        return "evt-1"


@dataclass
class _SceneStore:
    nodes: object = None
    edges: object = None


@dataclass
class _Stores:
    runtime: _Runtime
    world: _World
    lore: _Lore
    events: _Events
    scene: _SceneStore


class _Network:
    def locate(self, world_id, cue):
        class _L:
            scene = None

        return _L()

    def scene_inject_text(self, world_id, query=""):
        return ""

    def get(self, scene_id):
        return None


def test_snapshot_prefers_cached_scene_without_regen():
    from storyview.scene.composer import SceneComposer

    stores = _Stores(
        runtime=_Runtime(_snap="你在小酒馆，桌上有一杯水。"),
        world=_World(),
        lore=_Lore(),
        events=_Events(),
        scene=_SceneStore(),
    )
    composer = SceneComposer(stores, llm=None, scene_network=_Network())
    text = composer.snapshot("w1", cue="环顾四周")
    assert text == "你在小酒馆，桌上有一杯水。"


def test_compose_scene_uses_prior_snapshot_without_llm():
    from storyview.scene.composer import SceneComposer

    stores = _Stores(
        runtime=_Runtime(_snap="你在小酒馆，桌上有一杯水。"),
        world=_World(),
        lore=_Lore(),
        events=_Events(),
        scene=_SceneStore(),
    )
    composer = SceneComposer(stores, llm=None, scene_network=_Network())
    out = composer._compose_scene(
        world_row={"title": "测试世界"},
        canon={"prefer": []},
        cue="继续坐着",
        lore_rows=[],
        entities=[],
        world_time="",
        loc_id="loc-room",
        prior_snapshot=stores.runtime._snap,
    )
    assert "小酒馆" in out
    assert "一杯水" in out
