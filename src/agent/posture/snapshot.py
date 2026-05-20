from __future__ import annotations

from dataclasses import dataclass, field

from .fsm.state import PostureFsmState


@dataclass
class InteractionPostureSnapshot:
    """某 session 在 Agent 交互姿态层的可读快照。"""

    session_id: str
    state: PostureFsmState = field(default_factory=PostureFsmState.empty)
    meta: dict = field(default_factory=dict)

    @property
    def line_open(self) -> bool:
        return self.state.dialogue.line_open

    @property
    def proactive_intent_id(self) -> str:
        return self.state.dialogue.proactive_intent_id

    @property
    def in_scene(self) -> bool:
        return self.state.scene.in_scene

    @property
    def scene_admitted(self) -> bool:
        return self.state.scene.scene_admitted

    @property
    def scene_id(self) -> str:
        return self.state.scene.scene_id

    @property
    def scene_kind(self) -> str:
        return self.state.scene.scene_kind

    @property
    def scene_title(self) -> str:
        return self.state.scene.scene_title

    @property
    def stakes(self) -> str:
        return self.state.scene.stakes

    @property
    def interaction_id(self) -> str:
        return self.state.session.interaction_id

    @property
    def channel(self) -> str:
        return self.state.session.channel

    @property
    def turn_index(self) -> int:
        return self.state.session.turn_index

    @property
    def modality(self) -> str:
        return self.state.session.primary_modality

    def fsm_state(self) -> PostureFsmState:
        return self.state.copy()

    def apply_fsm_state(self, posture: PostureFsmState) -> None:
        self.state = posture.copy()

    def to_dict(self) -> dict:
        d = self.state.dialogue
        sc = self.state.scene
        sm = self.state.session
        return {
            "session_id": self.session_id,
            "line_open": d.line_open,
            "proactive_intent_id": d.proactive_intent_id,
            "in_scene": sc.in_scene,
            "scene_admitted": sc.scene_admitted,
            "scene_id": sc.scene_id,
            "scene_kind": sc.scene_kind,
            "scene_title": sc.scene_title,
            "stakes": sc.stakes,
            "interaction_id": sm.interaction_id,
            "channel": sm.channel,
            "turn_index": sm.turn_index,
            "modality": sm.primary_modality,
            "virtual_world_ref": sm.virtual_world_ref,
            "drone_ref": sm.drone_ref,
            "robot_dog_ref": sm.robot_dog_ref,
            "meta": dict(self.meta),
        }


DialoguePostureSnapshot = InteractionPostureSnapshot
