"""Agent 交互姿态层 — 对话/场景/会话的**结构态** FSM（非当下情绪、非 Speak 会话队列）。

职责：
- ``InteractionEvent`` → ``InteractionPosture.dispatch`` → 更新 line_open、场景进退、session 元数据等
- 与 ``agent.interaction`` 配套；由 ``DialogueKernel`` 驱动

与主产品路径的关系（截至当前仓库）：
- **Soul / Speak / WebUI 主路径未 import 本包**；线上对话走 ``speak/session`` + ``soul/presence``
- ``soul.presence.PresenceContext.line_open`` 由 Presence 自身 ``Expectation`` 推导，**不**读取本 FSM
- 保留用途：多模态交互内核（``DialogueKernel``）与 ``test/interaction``；删除前须连同 ``interaction`` 一并评估
"""

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
