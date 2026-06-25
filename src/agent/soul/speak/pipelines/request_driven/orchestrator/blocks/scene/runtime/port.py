from __future__ import annotations

from typing import Any, Protocol


class StorySceneReadPort(Protocol):
    """Storyview 场景叙事读口（duck-type StoryPort，speak 不依赖 storyview 实现）。"""

    def scene_inject_text(self, world_id: str, query: str = "") -> str: ...

    def locate_scene(
        self,
        world_id: str,
        query: str,
        *,
        current_scene_id: str | None = None,
    ) -> Any: ...

    def snapshot_scene(self, world_id: str, cue: str = "") -> str: ...


class StoryScenePort(StorySceneReadPort, Protocol):
    """Storyview 场景读写口：候选检索 + 场景应用。"""

    def locate_scene_candidates(
        self,
        world_id: str,
        query: str,
        *,
        limit: int = 3,
    ) -> list[Any]: ...

    def apply_scene(
        self,
        world_id: str,
        scene_id: str,
        *,
        transition_text: str = "",
    ) -> Any: ...
