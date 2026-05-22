from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TemporalityState:
    """存在与时间的感知：时间质感、在场深度与主观此刻。"""

    flow: str = ""
    depth: float = 0.5
    moment: str = ""
    duration_sense: str = ""

    def copy(self) -> TemporalityState:
        return TemporalityState(
            flow=self.flow,
            depth=self.depth,
            moment=self.moment,
            duration_sense=self.duration_sense,
        )

    def to_dict(self) -> dict:
        return {
            "flow": self.flow,
            "depth": self.depth,
            "moment": self.moment,
            "duration_sense": self.duration_sense,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TemporalityState:
        return cls(
            flow=str(d.get("flow", "")),
            depth=float(d.get("depth", 0.5)),
            moment=str(d.get("moment", "")),
            duration_sense=str(d.get("duration_sense", "")),
        )
