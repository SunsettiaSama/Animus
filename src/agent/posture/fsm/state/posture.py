from __future__ import annotations

from dataclasses import dataclass

from .dialogue import DialogueStance
from .scene import SceneStance
from .session import SessionMeta


@dataclass
class PostureFsmState:
    """Agent 对 session 的完整姿态快照（组合子状态，无扁平重复字段）。"""

    dialogue: DialogueStance
    scene: SceneStance
    session: SessionMeta

    @staticmethod
    def empty() -> PostureFsmState:
        return PostureFsmState(
            dialogue=DialogueStance(),
            scene=SceneStance(),
            session=SessionMeta(),
        )

    def copy(self) -> PostureFsmState:
        return PostureFsmState(
            dialogue=self.dialogue.copy(),
            scene=self.scene.copy(),
            session=self.session.copy(),
        )

    def reset_idle(self) -> None:
        self.dialogue.reset()
        self.scene.reset()
        self.session.reset()
