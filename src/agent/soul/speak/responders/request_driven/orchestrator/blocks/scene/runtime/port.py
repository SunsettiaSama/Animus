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

    def render_background(
        self,
        world_id: str,
        *,
        query: str = "",
        purpose: str = "",
    ) -> str: ...


class StoryScenePort(StorySceneReadPort, Protocol):
    """Storyview 场景读写口：候选检索 + 场景应用 + 编剧上放。"""

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
    ) -> str: ...

    def ask_gm_at_scene(
        self,
        world_id: str,
        scene_id: str,
        cue: str,
        *,
        kind: Any = None,
    ) -> Any: ...

    def answer_gm(
        self,
        question: Any,
        answer: Any,
        *,
        with_dice: bool = True,
    ) -> Any: ...
