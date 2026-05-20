"""姿态层有限状态机 — 对话/场景结构状态。"""

from .model import TERMINATING_EVENT_KINDS
from .scheduler import PostureFsmTransition, apply_transition
from .state import DialogueStance, PostureFsmState, SceneStance, SessionMeta
from .transition import (
    DIALOGUE_EVENT_KINDS,
    SCENE_EVENT_KINDS,
    apply_dialogue_transition,
    apply_scene_transition,
)

__all__ = [
    "DIALOGUE_EVENT_KINDS",
    "DialogueStance",
    "PostureFsmState",
    "PostureFsmTransition",
    "SceneStance",
    "SCENE_EVENT_KINDS",
    "SessionMeta",
    "TERMINATING_EVENT_KINDS",
    "apply_dialogue_transition",
    "apply_scene_transition",
    "apply_transition",
]
