"""语义连续性判定 — 硬规则 → embedding → LLM handler。"""

from .embedding_layer import EmbeddingContinuityJudge
from .llm_layer import LlmContinuityJudge
from .rules import RuleBasedContinuityJudge
from .signals import ContinuitySignals, build_signals
from .stack import DefaultContinuityJudge, StackedContinuityJudge
from .types import ContinuityDecision, ContinuityInput, ContinuityJudge, ContinuityVerdict

__all__ = [
    "ContinuityDecision",
    "ContinuityInput",
    "ContinuityJudge",
    "ContinuitySignals",
    "ContinuityVerdict",
    "DefaultContinuityJudge",
    "EmbeddingContinuityJudge",
    "LlmContinuityJudge",
    "RuleBasedContinuityJudge",
    "StackedContinuityJudge",
    "build_signals",
]
