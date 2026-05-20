"""Agent 交互姿态层 — 仅持有当前对话/场景结构状态。"""

from .events import InteractionEvent, InteractionEventKind
from .fsm import (
    DIALOGUE_EVENT_KINDS,
    DialogueStance,
    PostureFsmState,
    PostureFsmTransition,
    SceneStance,
    SCENE_EVENT_KINDS,
    SessionMeta,
    TERMINATING_EVENT_KINDS,
    apply_dialogue_transition,
    apply_scene_transition,
    apply_transition,
)
from .machine import (
    DialoguePosture,
    InteractionPosture,
    PostureTransitionResult,
)
from .snapshot import DialoguePostureSnapshot, InteractionPostureSnapshot

__all__ = [
    "DialoguePosture",
    "DialoguePostureSnapshot",
    "DIALOGUE_EVENT_KINDS",
    "DialogueStance",
    "InteractionEvent",
    "InteractionEventKind",
    "InteractionPosture",
    "InteractionPostureSnapshot",
    "PostureFsmState",
    "PostureFsmTransition",
    "SceneStance",
    "SCENE_EVENT_KINDS",
    "SessionMeta",
    "PostureTransitionResult",
    "TERMINATING_EVENT_KINDS",
    "apply_dialogue_transition",
    "apply_scene_transition",
    "apply_transition",
]
