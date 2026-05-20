from __future__ import annotations

from enum import Enum


class InteractionModalityKind(str, Enum):
    """Agent 与外界交互的形式（并列，无包含关系）。"""

    dialogue = "dialogue"
    virtual_world = "virtual_world"
    drone = "drone"
    robot_dog = "robot_dog"
