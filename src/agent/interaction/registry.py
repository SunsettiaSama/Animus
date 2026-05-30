from __future__ import annotations

from dataclasses import dataclass, field

from .dialogue.port import DialoguePort
from .drone.port import DronePort
from .kinds import InteractionModalityKind
from .robot_dog.port import RobotDogPort
from .virtual_world.port import VirtualWorldPort


@dataclass
class InteractionRegistry:
    """各模态 Port 注册表；当前无 Soul 侧自动填充，供未来多模态扩展或测试手动挂载。"""

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
