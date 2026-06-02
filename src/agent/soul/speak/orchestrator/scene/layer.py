from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakSceneLayer:
    """顶层叙事层：storyview 客观场景（第二人称），由 orchestrator/scene 注入。"""

    world_scene: str = ""
    scene_name: str = ""
    transition_text: str = ""
    matched_by: str = ""

    def render_blocks(self) -> list[str]:
        text = self.world_scene.strip()
        return [text] if text else []
