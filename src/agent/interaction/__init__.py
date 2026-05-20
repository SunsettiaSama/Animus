"""Agent 交互层 — Agent 与外界关系的顶层域。

- ``core``：SemanticInteraction、连续性（全模态共性）
- ``dialogue`` / ``virtual_world`` / ``drone`` / ``robot_dog``：并列交互形式

交互姿态层见 ``agent.posture``；期待驱动见 ``agent.soul.drive``。
"""

from .core import (
    AgentAction,
    AgentDialogue,
    AgentOutput,
    AgentOutputKind,
    AgentThought,
    AgentTraceRef,
    AgentUtterance,
    ContinuityDecision,
    ContinuityInput,
    ContinuityJudge,
    ContinuitySignals,
    ContinuityVerdict,
    DefaultContinuityJudge,
    EmbeddingContinuityJudge,
    Expectation,
    InteractionCloseReason,
    InteractionClosedEvent,
    InteractionContext,
    InteractionDirection,
    InteractionStatus,
    LlmContinuityJudge,
    RuleBasedContinuityJudge,
    SceneRef,
    SemanticInteraction,
    StackedContinuityJudge,
    UserStimulus,
    build_signals,
)
from agent.posture import (
    DialoguePosture,
    DialoguePostureSnapshot,
    DialogueStance,
    InteractionEvent,
    InteractionEventKind,
    InteractionPosture,
    InteractionPostureSnapshot,
    PostureTransitionResult,
)

from .dialogue import DialogueKernel, DialoguePort
from .drone import DronePort
from .kinds import InteractionModalityKind
from .registry import InteractionRegistry
from .robot_dog import RobotDogPort
from .virtual_world import VirtualWorldPort

__all__ = [
    "AgentAction",
    "AgentDialogue",
    "AgentOutput",
    "AgentOutputKind",
    "AgentThought",
    "AgentTraceRef",
    "AgentUtterance",
    "ContinuityDecision",
    "ContinuityInput",
    "ContinuityJudge",
    "ContinuitySignals",
    "ContinuityVerdict",
    "DefaultContinuityJudge",
    "DialoguePosture",
    "DialoguePostureSnapshot",
    "DialogueStance",
    "DialogueKernel",
    "DialoguePort",
    "DronePort",
    "EmbeddingContinuityJudge",
    "Expectation",
    "PostureTransitionResult",
    "InteractionCloseReason",
    "InteractionClosedEvent",
    "InteractionContext",
    "InteractionDirection",
    "InteractionEvent",
    "InteractionEventKind",
    "InteractionPosture",
    "InteractionPostureSnapshot",
    "InteractionModalityKind",
    "InteractionRegistry",
    "InteractionStatus",
    "LlmContinuityJudge",
    "RobotDogPort",
    "RuleBasedContinuityJudge",
    "SceneRef",
    "SemanticInteraction",
    "StackedContinuityJudge",
    "UserStimulus",
    "VirtualWorldPort",
    "build_signals",
]
