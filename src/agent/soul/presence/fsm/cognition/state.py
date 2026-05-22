from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CognitionState:
    """认知与思维：注意、负荷与当前思维线。"""

    focus: str = ""
    clarity: float = 0.5
    load: float = 0.0
    thread: str = ""
    uncertainty: float = 0.0

    def copy(self) -> CognitionState:
        return CognitionState(
            focus=self.focus,
            clarity=self.clarity,
            load=self.load,
            thread=self.thread,
            uncertainty=self.uncertainty,
        )

    def to_dict(self) -> dict:
        return {
            "focus": self.focus,
            "clarity": self.clarity,
            "load": self.load,
            "thread": self.thread,
            "uncertainty": self.uncertainty,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CognitionState:
        return cls(
            focus=str(d.get("focus", "")),
            clarity=float(d.get("clarity", 0.5)),
            load=float(d.get("load", 0.0)),
            thread=str(d.get("thread", "")),
            uncertainty=float(d.get("uncertainty", 0.0)),
        )
