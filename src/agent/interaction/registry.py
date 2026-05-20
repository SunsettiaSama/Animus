from __future__ import annotations

from dataclasses import dataclass, field

from .dialogue.port import DialoguePort
from .drone.port import DronePort
from .kinds import InteractionModalityKind
from .robot_dog.port import RobotDogPort
from .virtual_world.port import VirtualWorldPort


@dataclass
class InteractionRegistry:
    """各交互形式占位端口的注册表（并列挂载，互不包含）。"""

    dialogue: DialoguePort | None = None
    virtual_world: VirtualWorldPort | None = None
    drone: DronePort | None = None
    robot_dog: RobotDogPort | None = None
    _by_kind: dict[InteractionModalityKind, object] = field(
        default_factory=dict,
        repr=False,
    )

    def register(self, kind: InteractionModalityKind, port: object) -> None:
        self._by_kind[kind] = port
        if kind == InteractionModalityKind.dialogue:
            self.dialogue = port
        elif kind == InteractionModalityKind.virtual_world:
            self.virtual_world = port
        elif kind == InteractionModalityKind.drone:
            self.drone = port
        elif kind == InteractionModalityKind.robot_dog:
            self.robot_dog = port

    def get(self, kind: InteractionModalityKind) -> object | None:
        return self._by_kind.get(kind)
