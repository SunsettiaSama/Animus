from __future__ import annotations

from typing import Any

from .layer import SpeakSceneLayer
from .port import StorySceneReadPort
from .render import normalize_scene_inject, render_world_scene_block


def collect_story_scene(
    story_port: StorySceneReadPort,
    world_id: str,
    user_text: str,
) -> tuple[SpeakSceneLayer, dict[str, Any]]:
    """从 storyview 场景网络拉取叙述，组装为 orchestrator scene 层。"""
    query = user_text.strip()
    inject = story_port.scene_inject_text(world_id, query).strip()

    scene_name = ""
    transition_text = ""
    matched_by = ""
    scene_id: str | None = None

    locate = story_port.locate_scene(world_id, query)
    if locate.scene is not None:
        scene_name = locate.scene.name.strip()
        scene_id = locate.scene.id
    transition_text = str(getattr(locate, "transition_text", "") or "").strip()
    matched_by = str(getattr(locate, "matched_by", "") or "").strip()
    if not inject:
        fallback = str(getattr(locate, "inject_text", "") or "").strip()
        if fallback:
            inject = fallback

    if not inject:
        snapshot = story_port.snapshot_scene(world_id, cue=query).strip()
        if snapshot:
            inject = render_world_scene_block(snapshot)
            matched_by = matched_by or "snapshot"

    if inject:
        inject = normalize_scene_inject(inject)

    layer = SpeakSceneLayer(
        world_scene=inject,
        scene_name=scene_name,
        transition_text=transition_text,
        matched_by=matched_by,
    )
    meta: dict[str, Any] = {}
    if scene_id:
        meta["story_scene_id"] = scene_id
    if matched_by:
        meta["story_scene_matched_by"] = matched_by
    if scene_name:
        meta["story_scene_name"] = scene_name
    return layer, meta
