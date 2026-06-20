from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .enums import DialogueRhythm, normalize_rhythm


@dataclass(frozen=True)
class OutlineStep:
    label: str
    goal: str = ""
    done: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "goal": self.goal,
            "done": self.done,
        }


@dataclass
class DialogueOutline:
    steps: list[OutlineStep] = field(default_factory=list)
    current_step_index: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def current_step(self) -> OutlineStep | None:
        if not self.steps:
            return None
        idx = max(0, min(self.current_step_index, len(self.steps) - 1))
        return self.steps[idx]

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_step_index": self.current_step_index,
            "steps": [step.snapshot() for step in self.steps],
            "notes": list(self.notes),
        }


@dataclass
class RhythmState:
    phase: DialogueRhythm = "exchange"
    beat: int = 0
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "beat": self.beat,
            "notes": list(self.notes),
        }

    def set_phase(self, phase: str) -> None:
        self.phase = normalize_rhythm(phase)
