from __future__ import annotations

from storyview.network.query import SceneQueryEngine
from storyview.network.render import render_scene_inject
from storyview.network.scene_network import SceneNetwork
from storyview.types import SceneEdge, SceneUnit


class _MemoryNodeStore:
    def __init__(self) -> None:
        self._scenes: dict[str, SceneUnit] = {}

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
        _ = meta
        sid = scene_id or f"{world_id}-{len(self._scenes) + 1}"
        self._scenes[sid] = SceneUnit(
            id=sid,
            world_id=world_id,
            name=name,
            narrative=narrative,
            location_id=location_id,
            tags=tuple(tags or ()),
        )
        return sid

    def get(self, scene_id: str) -> SceneUnit | None:
        return self._scenes.get(scene_id)

    def list_by_world(self, world_id: str) -> list[SceneUnit]:
        return [scene for scene in self._scenes.values() if scene.world_id == world_id]

    def find_by_location(self, world_id: str, location_id: str) -> SceneUnit | None:
        for scene in self.list_by_world(world_id):
            if scene.location_id == location_id:
                return scene
        return None


class _MemoryEdgeStore:
    def __init__(self) -> None:
        self._edges: dict[str, SceneEdge] = {}
        self._counter = 0

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
        self._counter += 1
        eid = edge_id or f"edge-{self._counter}"
        self._edges[eid] = SceneEdge(
            id=eid,
            world_id=world_id,
            from_scene_id=from_scene_id,
            to_scene_id=to_scene_id,
            transition_text=transition_text,
            weight=weight,
        )
        return eid

    def out_edges(self, scene_id: str) -> list[SceneEdge]:
        return [edge for edge in self._edges.values() if edge.from_scene_id == scene_id]

    def list_by_world(self, world_id: str) -> list[SceneEdge]:
        return [edge for edge in self._edges.values() if edge.world_id == world_id]


class _RuntimeStub:
    def __init__(self, scene_id: str | None = None) -> None:
        self._scene_id = scene_id

    def resolve_current_scene_id(self, world_id: str) -> str | None:
        _ = world_id
        return self._scene_id


def _build_network(current_scene_id: str | None = None) -> SceneNetwork:
    nodes = _MemoryNodeStore()
    edges = _MemoryEdgeStore()
    inner_id = nodes.upsert(
        "w1",
        name="小酒馆内室",
        narrative="你看到右手边有个茶壶，正前方是一道门。",
        scene_id="scene-inner",
        tags=["酒馆"],
    )
    bamboo_id = nodes.upsert(
        "w1",
        name="青竹坞",
        narrative="你站在竹林边缘，风过处竹叶沙沙作响。",
        scene_id="scene-bamboo",
        tags=["竹林"],
    )
    edges.link(
        "w1",
        from_scene_id=inner_id,
        to_scene_id=bamboo_id,
        transition_text="出门后，沿小路走十公里，会来到一片竹林，叫青竹坞。",
    )
    return SceneNetwork(nodes, edges, runtime=_RuntimeStub(current_scene_id))


def test_locate_current_scene_without_query():
    network = _build_network("scene-inner")
    result = network.locate("w1", "")
    assert result.scene is not None
    assert result.scene.id == "scene-inner"
    assert "茶壶" in result.inject_text
    assert result.matched_by == "current"


def test_locate_scene_by_name():
    network = _build_network(None)
    result = network.locate("w1", "青竹坞")
    assert result.scene is not None
    assert result.scene.name == "青竹坞"
    assert "竹叶" in result.inject_text
    assert result.matched_by == "scene_name"


def test_locate_via_edge_transition():
    network = _build_network("scene-inner")
    result = network.locate("w1", "竹林")
    assert result.scene is not None
    assert result.scene.id == "scene-bamboo"
    assert "十公里" in result.transition_text
    assert "十公里" in result.inject_text
    assert result.matched_by == "edge"


def test_render_scene_inject_adds_header():
    network = _build_network("scene-inner")
    text = network.scene_inject_text("w1", "")
    assert text.startswith("【你所处的场景】")
    assert "茶壶" in text


def test_query_engine_scores_narrative():
    engine = SceneQueryEngine()
    scenes = [
        SceneUnit(
            id="a",
            world_id="w1",
            name="甲",
            narrative="壁炉噼啪作响",
        ),
        SceneUnit(
            id="b",
            world_id="w1",
            name="乙",
            narrative="海风咸湿",
        ),
    ]
    result = engine.locate("w1", "壁炉", scenes=scenes, edges=[])
    assert result.scene is not None
    assert result.scene.id == "a"
    rendered = render_scene_inject(result)
    assert rendered.startswith("【你所处的场景】")


def test_locate_candidates_returns_ranked_top_three():
    network = _build_network("scene-inner")
    candidates = network.locate_candidates("w1", "竹林")
    assert 1 <= len(candidates) <= 3
    assert candidates[0].scene.id == "scene-bamboo"
    assert candidates[0].matched_by == "edge"
    assert "十公里" in candidates[0].transition_text


def test_locate_candidates_falls_back_to_current():
    network = _build_network("scene-inner")
    candidates = network.locate_candidates("w1", "")
    assert len(candidates) == 1
    assert candidates[0].scene.id == "scene-inner"
    assert candidates[0].matched_by == "current"
