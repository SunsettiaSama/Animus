"""交互共性层 — 最小语义单元、连续性；与具体模态（dialogue / drone / …）并列在上层之下。"""

from .continuity import (
    ContinuityDecision,
    ContinuityInput,
    ContinuityJudge,
    ContinuitySignals,
    ContinuityVerdict,
    DefaultContinuityJudge,
    EmbeddingContinuityJudge,
    LlmContinuityJudge,
    RuleBasedContinuityJudge,
    StackedContinuityJudge,
    build_signals,
)
from .context import InteractionContext, SceneRef
from .events import InteractionClosedEvent
from .expectation import Expectation
from .outputs import (
    AgentAction,
    AgentDialogue,
    AgentOutput,
    AgentOutputKind,
    AgentThought,
)
from .segments import AgentTraceRef, AgentUtterance, InteractionDirection, UserStimulus
from .semantic import InteractionCloseReason, InteractionStatus, SemanticInteraction

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
    "EmbeddingContinuityJudge",
    "Expectation",
    "InteractionCloseReason",
    "InteractionClosedEvent",
    "InteractionContext",
    "InteractionDirection",
    "InteractionStatus",
    "LlmContinuityJudge",
    "RuleBasedContinuityJudge",
    "SceneRef",
    "SemanticInteraction",
    "StackedContinuityJudge",
    "UserStimulus",
    "build_signals",
]
