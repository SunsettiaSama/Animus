"""Agent 交互层 — 全模态「语义交互 + 连续性」抽象（与 Soul 域并列，非 Soul 子模块）。

子包：
- ``core``：``SemanticInteraction``、连续性判断（embedding / LLM / 规则栈）
- ``dialogue`` / ``virtual_world`` / ``drone`` / ``robot_dog``：各模态 Port 与 ``DialogueKernel``

分层约定：
- **结构态** → ``agent.posture``（对话线、场景）
- **当下态** → ``agent.soul.presence``（情感、期待、冲动）
- **对话编排** → ``agent.soul.speak``（compose、流式出站、session 队列）

接线状态：
- ``DialogueKernel`` 仅在 ``test/interaction`` 实例化；**未**接入 ``SoulService`` / ``SpeakService``
- 若只维护 WebUI 对话，可忽略本包；接入多模态时再在 Soul 显式构造 Kernel 或合并进 Speak
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
