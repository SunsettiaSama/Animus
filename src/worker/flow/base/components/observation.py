from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ObservationMode(str, Enum):
    full = "full"
    distilled = "distilled"


@dataclass(frozen=True)
class TaoStep:
    index: int
    thought: str
    action: str
    action_input: Any
    observation: str


@dataclass
class NodeObservation:
    task_id: str
    mode: ObservationMode
    steps: list[TaoStep]
    summary: str
    step_count: int
    key_decisions: list[str] = field(default_factory=list)
    verification_report: str = ""   # 由 VerificationResult.to_planner_report() 填入

    def to_planner_context(self) -> str:
        if self.mode == ObservationMode.full:
            return self._format_full()
        return self._format_distilled()

    def _format_full(self) -> str:
        lines = [f"[Node {self.task_id}] total_steps={self.step_count}"]
        for s in self.steps:
            lines += [
                f"  Step {s.index}:",
                f"    Thought:     {s.thought}",
                f"    Action:      {s.action}",
                f"    Observation: {s.observation}",
            ]
        lines.append(f"  Summary: {self.summary}")
        if self.verification_report:
            lines.append(f"  Verification: {self.verification_report}")
        return "\n".join(lines)

    def _format_distilled(self) -> str:
        lines = [
            f"[Node {self.task_id}] total_steps={self.step_count}",
            f"  Summary: {self.summary}",
        ]
        if self.key_decisions:
            lines.append("  Key decisions:")
            for kd in self.key_decisions:
                lines.append(f"    - {kd}")
        if self.verification_report:
            lines.append(f"  Verification: {self.verification_report}")
        return "\n".join(lines)
