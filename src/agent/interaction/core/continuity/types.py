from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..semantic import SemanticInteraction


class ContinuityVerdict(str, Enum):
    continue_same = "continue_same"
    close_and_new = "close_and_new"
    close_only = "close_only"


@dataclass(frozen=True)
class ContinuityDecision:
    """连续性裁决结果（可观测、可日志）。"""

    verdict: ContinuityVerdict
    reason: str = ""
    layer: str = "rule"
    confidence: float = 1.0


@dataclass(frozen=True)
class ContinuityInput:
    active: SemanticInteraction | None
    incoming_user_text: str = ""
    incoming_agent_intent: str = ""
    now_iso: str = ""


class ContinuityJudge(Protocol):
    def judge(self, data: ContinuityInput) -> ContinuityDecision: ...
