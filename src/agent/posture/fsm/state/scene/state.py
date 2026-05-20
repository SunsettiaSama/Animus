from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SceneStance:
    """交织场结构状态（行为门控）。"""

    in_scene: bool = False
    scene_admitted: bool = False
    scene_id: str = ""
    scene_kind: str = ""
    scene_title: str = ""
    stakes: str = ""

    def copy(self) -> SceneStance:
        return SceneStance(
            in_scene=self.in_scene,
            scene_admitted=self.scene_admitted,
            scene_id=self.scene_id,
            scene_kind=self.scene_kind,
            scene_title=self.scene_title,
            stakes=self.stakes,
        )

    def reset(self) -> None:
        self.in_scene = False
        self.scene_admitted = False
        self.scene_id = ""
        self.scene_kind = ""
        self.scene_title = ""
        self.stakes = ""
