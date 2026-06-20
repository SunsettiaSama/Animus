from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .collect import collect_story_scene
from .port import StorySceneReadPort

if TYPE_CHECKING:
    from ..bundle import SpeakPromptBundle


def apply_story_scene(
    bundle: SpeakPromptBundle,
    *,
    story_port: StorySceneReadPort | None,
    world_id_fn: Callable[[], str] | None,
    user_text: str,
) -> None:
    """将 storyview 场景叙事写入 bundle.scene，供 orchestrator 统一编排。"""
    if bundle.meta.get("scene_compose_version"):
        return
    if story_port is None or world_id_fn is None:
        return
    world_id = world_id_fn().strip()
    if not world_id:
        return

    layer, meta = collect_story_scene(story_port, world_id, user_text)
    if not layer.world_scene.strip():
        return

    bundle.scene = layer
    bundle.meta.update(meta)
    if layer.matched_by:
        bundle.notes.append(f"story_scene: matched_by={layer.matched_by}")
