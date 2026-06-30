from __future__ import annotations

from typing import Protocol

from storyview.scene.network.query import SceneQueryEngine
from storyview.scene.network.render import build_inject_text, render_scene_inject
from storyview.types import SceneCandidate, SceneEdge, SceneLocateResult, SceneUnit


class SceneNodeReadPort(Protocol):
    def get(self, scene_id: str) -> SceneUnit | None: ...
    def list_by_world(self, world_id: str) -> list[SceneUnit]: ...
    def find_by_location(self, world_id: str, location_id: str) -> SceneUnit | None: ...
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
    ) -> str: ...


class SceneEdgeReadPort(Protocol):
    def out_edges(self, scene_id: str) -> list[SceneEdge]: ...
    def in_edges(self, scene_id: str) -> list[SceneEdge]: ...
    def link(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
        edge_id: str | None = None,
    ) -> str: ...
    def list_by_world(self, world_id: str) -> list[SceneEdge]: ...


class SceneRuntimePort(Protocol):
    def resolve_current_scene_id(self, world_id: str) -> str | None: ...


class SceneNetwork:
    """场景图网络：节点叙述 + 边转化 + 检索定位。"""

    def __init__(
        self,
        nodes: SceneNodeReadPort,
        edges: SceneEdgeReadPort,
        *,
        runtime: SceneRuntimePort | None = None,
        query: SceneQueryEngine | None = None,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._runtime = runtime
        self._query = query or SceneQueryEngine()

    def upsert_scene(
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
        return self._nodes.upsert(
            world_id,
            name=name,
            narrative=narrative,
            location_id=location_id,
            tags=tags,
            scene_id=scene_id,
            meta=meta,
        )

    def link_scenes(
        self,
        world_id: str,
        *,
        from_scene_id: str,
        to_scene_id: str,
        transition_text: str,
        weight: int = 10,
        edge_id: str | None = None,
    ) -> str:
        return self._edges.link(
            world_id,
            from_scene_id=from_scene_id,
            to_scene_id=to_scene_id,
            transition_text=transition_text,
            weight=weight,
            edge_id=edge_id,
        )

    def get(self, scene_id: str) -> SceneUnit | None:
        return self._nodes.get(scene_id)

    def list_scenes(self, world_id: str) -> list[SceneUnit]:
        return self._nodes.list_by_world(world_id)

    def out_edges(self, scene_id: str) -> list[SceneEdge]:
        return self._edges.out_edges(scene_id)

    def in_edges(self, scene_id: str) -> list[SceneEdge]:
        if hasattr(self._edges, "in_edges"):
            return self._edges.in_edges(scene_id)  # type: ignore[attr-defined]
        return []

    def neighbor_scenes(
        self,
        world_id: str,
        scene_id: str,
        *,
        depth: int = 1,
    ) -> list[tuple[SceneUnit, SceneEdge, str]]:
        if depth < 1:
            return []
        scene_by_id = {scene.id: scene for scene in self._nodes.list_by_world(world_id)}
        visited = {scene_id}
        frontier = {scene_id}
        neighbors: list[tuple[SceneUnit, SceneEdge, str]] = []
        for _ in range(depth):
            next_frontier: set[str] = set()
            for current_id in frontier:
                for edge in self.out_edges(current_id):
                    target = scene_by_id.get(edge.to_scene_id)
                    if target is not None and target.id not in visited:
                        neighbors.append((target, edge, "out"))
                        visited.add(target.id)
                        next_frontier.add(target.id)
                for edge in self.in_edges(current_id):
                    source = scene_by_id.get(edge.from_scene_id)
                    if source is not None and source.id not in visited:
                        neighbors.append((source, edge, "in"))
                        visited.add(source.id)
                        next_frontier.add(source.id)
            frontier = next_frontier
            if not frontier:
                break
        return neighbors

    def search_scenes(
        self,
        world_id: str,
        *,
        name: str = "",
        tag: str = "",
        text: str = "",
        limit: int = 10,
    ) -> list[SceneUnit]:
        name_q = name.strip().lower()
        tag_q = tag.strip().lower()
        text_q = text.strip().lower()
        matched: list[SceneUnit] = []
        for scene in self._nodes.list_by_world(world_id):
            if name_q and name_q not in scene.name.lower():
                continue
            if tag_q and not any(tag_q in item.lower() for item in scene.tags):
                continue
            if text_q:
                haystack = " ".join([scene.name, scene.narrative, " ".join(scene.tags)]).lower()
                if text_q not in haystack:
                    continue
            matched.append(scene)
            if len(matched) >= limit:
                break
        return matched

    def resolve_current_scene_id(self, world_id: str) -> str | None:
        if self._runtime is None:
            return None
        return self._runtime.resolve_current_scene_id(world_id)

    def locate(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> SceneLocateResult:
        resolved_current = current_scene_id
        if resolved_current is None:
            resolved_current = self.resolve_current_scene_id(world_id)
        scenes = self._nodes.list_by_world(world_id)
        edges = self._edges.list_by_world(world_id)
        result = self._query.locate(
            world_id,
            query,
            scenes=scenes,
            edges=edges,
            current_scene_id=resolved_current,
        )
        if not result.inject_text.strip() and result.scene is not None:
            inject = build_inject_text(result.scene, transition_text=result.transition_text)
            return SceneLocateResult(
                scene=result.scene,
                transition_text=result.transition_text,
                inject_text=inject,
                matched_by=result.matched_by,
            )
        return result

    def scene_inject_text(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> str:
        result = self.locate(world_id, query, current_scene_id=current_scene_id)
        return render_scene_inject(result)

    def locate_candidates(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
        limit: int = 3,
    ) -> list[SceneCandidate]:
        resolved_current = current_scene_id
        if resolved_current is None:
            resolved_current = self.resolve_current_scene_id(world_id)
        scenes = self._nodes.list_by_world(world_id)
        edges = self._edges.list_by_world(world_id)
        return self._query.locate_candidates(
            world_id,
            query,
            scenes=scenes,
            edges=edges,
            current_scene_id=resolved_current,
            limit=limit,
        )
