from __future__ import annotations

from dataclasses import dataclass, field

from agent.interaction.kinds import InteractionModalityKind


@dataclass
class SessionMeta:
    """会话元数据 — 不参与期待定义，仅供绑定、观测与模态占位。"""

    interaction_id: str = ""
    channel: str = ""
    turn_index: int = 0
    primary_modality: str = InteractionModalityKind.dialogue.value
    virtual_world_ref: str = ""
    drone_ref: str = ""
    robot_dog_ref: str = ""
    hints: dict = field(default_factory=dict)

    def copy(self) -> SessionMeta:
        return SessionMeta(
            interaction_id=self.interaction_id,
            channel=self.channel,
            turn_index=self.turn_index,
            primary_modality=self.primary_modality,
            virtual_world_ref=self.virtual_world_ref,
            drone_ref=self.drone_ref,
            robot_dog_ref=self.robot_dog_ref,
            hints=dict(self.hints),
        )

    def reset(self) -> None:
        self.interaction_id = ""
        self.channel = ""
        self.turn_index = 0
        self.primary_modality = InteractionModalityKind.dialogue.value
        self.virtual_world_ref = ""
        self.drone_ref = ""
        self.robot_dog_ref = ""
        self.hints = {}
